namespace NightreignP2PHelper;

internal enum IdentitySessionResult { Idle, Rejected, Unavailable, Completed, RecoveryPending }

internal readonly record struct IdentityRequestEnvironment(
    DateTimeOffset Now, bool ClientAlive, bool Cancelled, bool GameRunning);

// Each bounded recovery attempt owns one Steam session. All its observations
// finish before shutdown; durable journals, rather than an idle SDK connection,
// retain compensation ownership between network retries.
internal static class IdentitySessionCoordinator
{
    internal static void Release(ref bool initialized, Action shutdown)
    {
        // Steamworks.NET's Shutdown decrements its callback dispatcher count.
        // Calling it after a failed Init poisons the next successful session.
        if (!initialized) return;
        try { shutdown(); }
        finally { initialized = false; }
    }

    internal static void ReleaseResources(IEnumerable<Action> cleanup)
    {
        Exception? first = null;
        foreach (var release in cleanup)
        {
            try { release(); }
            catch (Exception failure) { first ??= failure; }
        }
        if (first is not null) throw first;
    }

    internal static IdentitySessionResult RunRecoveryAttempt(Func<bool> connect,
        Func<bool> recover, Action disconnect)
    {
        try
        {
            if (!connect()) return IdentitySessionResult.Unavailable;
            return recover() ? IdentitySessionResult.Completed : IdentitySessionResult.RecoveryPending;
        }
        finally { disconnect(); }
    }

    internal static IdentitySessionResult Run(IdentityRequest? request, bool recoveryRequired,
        Func<IdentityRequest, IdentityRequestEnvironment> inspect,
        Func<bool> connect, Action work, Action disconnect)
    {
        if (!recoveryRequired)
        {
            if (request is null) return IdentitySessionResult.Idle;
            if (!CanStart(request, inspect(request))) return IdentitySessionResult.Rejected;
        }
        try
        {
            if (!connect()) return IdentitySessionResult.Unavailable;
            // Login/initialization can take long enough for a queued request to
            // expire, be cancelled, or lose its game. Recheck before any action.
            if (!recoveryRequired && !CanStart(request!, inspect(request!))) return IdentitySessionResult.Rejected;
            work();
            return IdentitySessionResult.Completed;
        }
        finally { disconnect(); }
    }

    private static bool CanStart(IdentityRequest request, IdentityRequestEnvironment context)
        => Guid.TryParseExact(request.Transaction, "N", out _)
        && Guid.TryParseExact(request.Client, "N", out _)
        && IdentityRules.ValidSteamId(request.Target)
        && IdentityRules.ValidSteamId(request.ExpectedAccount) && request.ExpectedAccount != request.Target
        && context.Now - request.CreatedAt <= TimeSpan.FromSeconds(15)
        && request.CreatedAt <= context.Now.AddSeconds(5)
        && context.ClientAlive && !context.Cancelled && context.GameRunning;
}
