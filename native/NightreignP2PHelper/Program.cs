using System.Diagnostics;
using System.Runtime.InteropServices;
using Steamworks;

namespace NightreignP2PHelper;

internal static class Program
{
    private const string GameProcessName = "nightreign";
    private const string NightreignAppId = "2622380";
    private static nint _steamApiHandle;
    private static bool _resolverInstalled;

    public static async Task<int> Main(string[] args)
    {
        Console.OutputEncoding = System.Text.Encoding.UTF8;
        Console.InputEncoding = System.Text.Encoding.UTF8;

        using var cancellation = new CancellationTokenSource();
        Console.CancelKeyPress += (_, eventArgs) =>
        {
            eventArgs.Cancel = true;
            cancellation.Cancel();
        };
        var etwEnabled = args.Any(arg => arg.Equals("--etw", StringComparison.OrdinalIgnoreCase));
        Protocol.SetEtwState(etwEnabled ? "waiting" : "disabled");
        // Console.In is a synchronized TextReader. On Windows its ReadLineAsync()
        // can block before returning a Task when stdin is a QProcess pipe, which
        // would prevent the game-detection loop from ever starting. Keep all
        // blocking stdin work on a dedicated pool thread.
        _ = StartShutdownMonitor(Console.In, cancellation);

        Protocol.Status("waiting_for_game", "等待 nightreign.exe", force: true);
        try
        {
            while (!cancellation.IsCancellationRequested)
            {
                using var game = FindGameProcess();
                if (game is null)
                {
                    await Delay(cancellation.Token);
                    continue;
                }

                return await RunGameSession(game, etwEnabled, cancellation.Token);
            }
        }
        catch (OperationCanceledException)
        {
            // The parent closed while the helper was waiting for the game.
        }

        return 0;
    }

    private static async Task<int> RunGameSession(
        Process game,
        bool etwEnabled,
        CancellationToken cancellationToken)
    {
        Environment.SetEnvironmentVariable("SteamAppId", NightreignAppId);
        Environment.SetEnvironmentVariable("SteamGameId", NightreignAppId);

        try
        {
            var steamApiPath = SteamPathResolver.FindNightreignSteamApi(game);
            if (steamApiPath is null || !File.Exists(steamApiPath))
            {
                Protocol.Status("steam_api_error", "未在黑夜君临目录找到 steam_api64.dll", force: true);
                return 2;
            }
            _steamApiHandle = NativeLibrary.Load(steamApiPath);
            if (!_resolverInstalled)
            {
                NativeLibrary.SetDllImportResolver(typeof(SteamAPI).Assembly, (libraryName, _, _) =>
                    libraryName.StartsWith("steam_api64", StringComparison.OrdinalIgnoreCase)
                        ? _steamApiHandle
                        : 0);
                _resolverInstalled = true;
            }

            if (!SteamAPI.Init())
            {
                Protocol.Status("steam_api_error", "SteamAPI 初始化失败，请确认 Steam 已登录", force: true);
                ReleaseSteamApiLibrary();
                return 2;
            }
        }
        catch (Exception ex)
        {
            Protocol.LogError(ex.ToString());
            Protocol.Status("steam_api_error", $"SteamAPI 初始化异常：{ex.Message}", force: true);
            ReleaseSteamApiLibrary();
            return 2;
        }

        EtwPingMonitor? etw = null;
        string? etwError = null;
        if (etwEnabled)
        {
            Protocol.SetEtwState("starting");
            try
            {
                etw = new EtwPingMonitor();
                etw.Start();
                Protocol.SetEtwState("ready");
            }
            catch (Exception ex)
            {
                etw?.Dispose();
                etw = null;
                etwError = ex.Message;
                Protocol.SetEtwState("error");
                Protocol.LogError($"ETW latency detection unavailable: {ex}");
            }
        }

        Protocol.Status("steam_ready", BuildReadyMessage(etwEnabled, etwError), force: true);
        var reader = new SteamPeerReader(etw);

        try
        {
            while (!cancellationToken.IsCancellationRequested && !game.HasExited)
            {
                Protocol.Snapshot(reader.ReadPeers());
                await Delay(cancellationToken);
            }
        }
        catch (OperationCanceledException)
        {
            // Normal shutdown.
        }
        catch (Exception ex)
        {
            Protocol.LogError(ex.ToString());
            Protocol.Status("runtime_error", $"读取 Steam 连接失败：{ex.Message}", force: true);
            return 3;
        }
        finally
        {
            etw?.Dispose();
            SteamAPI.Shutdown();
            ReleaseSteamApiLibrary();
        }

        return 0;
    }

    private static string BuildReadyMessage(bool etwEnabled, string? etwError)
    {
        var parts = new List<string> { "SteamAPI 已连接" };
        if (etwEnabled)
            parts.Add(etwError is null ? "ETW 延迟检测已启用" : $"ETW 不可用：{etwError}");
        return string.Join("，", parts);
    }

    private static Process? FindGameProcess()
    {
        try
        {
            return Process.GetProcessesByName(GameProcessName).FirstOrDefault(process => !process.HasExited);
        }
        catch
        {
            return null;
        }
    }

    private static void ReleaseSteamApiLibrary()
    {
        if (_steamApiHandle == 0)
            return;
        NativeLibrary.Free(_steamApiHandle);
        _steamApiHandle = 0;
    }

    internal static Task StartShutdownMonitor(TextReader input, CancellationTokenSource cancellation)
    {
        return Task.Run(() => MonitorParentInput(input, cancellation));
    }

    private static void MonitorParentInput(TextReader input, CancellationTokenSource cancellation)
    {
        try
        {
            string? line;
            while ((line = input.ReadLine()) is not null)
            {
                if (line.Trim().Equals("shutdown", StringComparison.OrdinalIgnoreCase))
                    break;
            }
        }
        catch
        {
            // Closing stdin is also a shutdown request.
        }
        cancellation.Cancel();
    }

    private static async Task Delay(CancellationToken cancellationToken)
    {
        await Task.Delay(TimeSpan.FromSeconds(1), cancellationToken);
    }
}
