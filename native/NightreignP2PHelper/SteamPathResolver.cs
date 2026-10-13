using System.Diagnostics;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace NightreignP2PHelper;

internal static class SteamPathResolver
{
    private static readonly Regex LibraryPathRegex = new(
        "\\\"path\\\"\\s+\\\"(?<path>[^\\\"]+)\\\"",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);
    private static readonly Regex InstallDirRegex = new(
        "\\\"installdir\\\"\\s+\\\"(?<dir>[^\\\"]+)\\\"",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    public static string? FindSteamRoot()
    {
        try
        {
            foreach (var process in Process.GetProcessesByName("steam"))
            {
                using (process)
                {
                    var path = process.MainModule?.FileName;
                    if (!string.IsNullOrWhiteSpace(path))
                        return Path.GetDirectoryName(path);
                }
            }
        }
        catch (Exception ex)
        {
            Protocol.LogError($"Unable to inspect steam.exe: {ex.Message}");
        }

        foreach (var valueName in new[] { "SteamPath", "InstallPath" })
        {
            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(@"Software\Valve\Steam");
                if (key?.GetValue(valueName) is string path && Directory.Exists(path))
                    return path.Replace('/', Path.DirectorySeparatorChar);
            }
            catch (Exception ex)
            {
                Protocol.LogError($"Unable to read Steam registry path: {ex.Message}");
            }
        }

        var programFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
        var defaultPath = Path.Combine(programFilesX86, "Steam");
        return Directory.Exists(defaultPath) ? defaultPath : null;
    }

    public static string? FindNightreignSteamApi(Process game)
    {
        try
        {
            var processDirectory = Path.GetDirectoryName(game.MainModule?.FileName);
            var processDll = processDirectory is null
                ? null
                : Path.Combine(processDirectory, "steam_api64.dll");
            if (processDll is not null && File.Exists(processDll))
                return processDll;
        }
        catch (Exception ex)
        {
            // EAC can deny MainModule access to a non-elevated helper. Steam's app
            // manifest below provides a read-only path lookup without elevation.
            Protocol.LogError($"Unable to inspect nightreign.exe path: {ex.Message}");
        }

        var steamRoot = FindSteamRoot();
        if (steamRoot is null)
            return null;

        foreach (var library in EnumerateSteamLibraries(steamRoot))
        {
            var steamApps = Path.Combine(library, "steamapps");
            var manifest = Path.Combine(steamApps, "appmanifest_2622380.acf");
            var installDirectory = ReadInstallDirectory(manifest);
            if (installDirectory is null)
                continue;

            var installRoot = Path.Combine(steamApps, "common", installDirectory);
            foreach (var relativePath in new[] { Path.Combine("Game", "steam_api64.dll"), "steam_api64.dll" })
            {
                var candidate = Path.Combine(installRoot, relativePath);
                if (File.Exists(candidate))
                    return candidate;
            }
        }

        return null;
    }

    internal static IReadOnlyList<string> EnumerateSteamLibraries(string steamRoot)
    {
        var libraries = new List<string> { steamRoot };
        var libraryFile = Path.Combine(steamRoot, "steamapps", "libraryfolders.vdf");
        try
        {
            if (!File.Exists(libraryFile))
                return libraries;

            foreach (Match match in LibraryPathRegex.Matches(File.ReadAllText(libraryFile)))
            {
                var path = match.Groups["path"].Value.Replace("\\\\", "\\");
                if (!string.IsNullOrWhiteSpace(path)
                    && !libraries.Contains(path, StringComparer.OrdinalIgnoreCase))
                    libraries.Add(path);
            }
        }
        catch (Exception ex)
        {
            Protocol.LogError($"Unable to parse Steam library folders: {ex.Message}");
        }
        return libraries;
    }

    internal static string? ReadInstallDirectory(string manifestPath)
    {
        try
        {
            if (!File.Exists(manifestPath))
                return null;
            var match = InstallDirRegex.Match(File.ReadAllText(manifestPath));
            return match.Success ? match.Groups["dir"].Value : null;
        }
        catch (Exception ex)
        {
            Protocol.LogError($"Unable to parse Nightreign app manifest: {ex.Message}");
            return null;
        }
    }

}
