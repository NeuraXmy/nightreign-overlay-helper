using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;
using Steamworks;

namespace NightreignP2PHelper;

internal static class CommendationWorker
{
    internal static int Run()
    {
        nint library = 0;
        bool initialized = false;
        CommendationResult result = new("error");
        Process? game = null;
        try
        {
            var line = Console.ReadLine();
            var request = line is { Length: <= 8192 }
                ? JsonSerializer.Deserialize<CommendationRequest>(line, CommendationHistory.Json) : null;
            if (!CommendationEngine.ValidRequest(request)) return Reply(result);
            Directory.CreateDirectory(IdentityFiles.Root);
            // A hold/recovery task owns this same lock throughout its transaction.
            // Never post concurrently with communication restoration for that player.
            using var communicationLock = new FileStream(Path.Combine(IdentityFiles.Root,
                "target-" + request!.ExpectedAccount + "-" + request.Target + ".lock"),
                FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            foreach (var candidate in Process.GetProcessesByName("nightreign"))
            {
                if (game is null && !candidate.HasExited) game = candidate;
                else candidate.Dispose();
            }
            // Never start a new Steam game presence after the actual game has closed.
            if (game is null) return Reply(result);
            var path = SteamPathResolver.FindNightreignSteamApi(game);
            if (path is null || !File.Exists(path)) return Reply(result);
            Environment.SetEnvironmentVariable("SteamAppId", "2622380");
            Environment.SetEnvironmentVariable("SteamGameId", "2622380");
            library = NativeLibrary.Load(path);
            NativeLibrary.SetDllImportResolver(typeof(SteamAPI).Assembly, (name, _, _) =>
                name.StartsWith("steam_api64", StringComparison.OrdinalIgnoreCase) ? library : 0);
            initialized = SteamAPI.Init();
            if (!initialized) return Reply(result);
            var account = SteamUser.GetSteamID().ToString();
            void EnsureActive()
            {
                if (game.HasExited || !SteamUser.BLoggedOn() || SteamUser.GetSteamID().ToString() != account)
                    throw new OperationCanceledException();
            }
            EnsureActive();
            var directory = Environment.GetEnvironmentVariable("NROH_COMMENDATION_DIR")
                ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "NightreignOverlayHelper", "identity", "commendations");
            result = CommendationEngine.Send(request!, account, directory,
                () => new SteamCommentSession(account, request!.Target, EnsureActive));
            return Reply(result);
        }
        catch { return Reply(result); }
        finally
        {
            if (initialized) SteamAPI.Shutdown();
            if (library != 0) NativeLibrary.Free(library);
            game?.Dispose();
        }
    }

    private static int Reply(CommendationResult result)
    {
        Console.WriteLine(JsonSerializer.Serialize(result, CommendationHistory.Json));
        Console.Out.Flush();
        return result.State == "error" ? 1 : 0;
    }
}
