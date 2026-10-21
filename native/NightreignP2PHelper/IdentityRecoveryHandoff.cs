using System.Diagnostics;

namespace NightreignP2PHelper;

// Pending compensation belongs to durable journals. A supervisor that never
// initializes Steam starts finite task children only after this local backoff.
internal static class IdentityRecoveryHandoff
{
    internal const int ClientLeaseMs = 30_000;
    internal const int BrowserWatchdogMs = 90_000;
    internal const int RetryMs = 15_000;
    private sealed record Retry(DateTimeOffset NotBefore);
    private static string RetryPath(string root) => Path.Combine(root, "next-recovery.json");

    internal static bool FreshClient(DateTimeOffset modified, DateTimeOffset now)
        => modified <= now.AddSeconds(5) && now - modified < TimeSpan.FromMilliseconds(ClientLeaseMs);

    internal static int RemainingDelay(string root, DateTimeOffset now)
    {
        var retry = IdentityFiles.Read<Retry>(RetryPath(root));
        return retry is null ? 0 : (int)Math.Clamp((retry.NotBefore - now).TotalMilliseconds, 0, RetryMs);
    }

    internal static void Schedule(string root, DateTimeOffset now, Action startSuccessor)
    {
        // Commit before launching: any concurrently started worker observes the
        // same cooldown and cannot immediately reconnect as the old process exits.
        IdentityFiles.Write(RetryPath(root), new Retry(now.AddMilliseconds(RetryMs)));
        startSuccessor();
    }

    internal static FileStream? TakeWorkerLock(string root, int waitMs = 0)
    {
        var clock = Stopwatch.StartNew();
        while (true)
        {
            try { return new FileStream(Path.Combine(root, "worker.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
            catch (IOException) when (clock.ElapsedMilliseconds < waitMs) { Thread.Sleep(50); }
            catch (IOException) { return null; }
        }
    }
}
