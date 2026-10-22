namespace NightreignP2PHelper;

// Kept independent of Steam for offline failure/restart tests against the same
// recovery driver used by the detached production worker.
internal interface IIdentityRecoveryChannel
{
    bool AccountMatches { get; }
    bool BlockSettled { get; }
    int Relationship { get; }
    IdentityPage Inspect(int timeoutMs = 12000);
    bool Restore();
    void Wait(int milliseconds);
}

internal static class IdentityRecoveryEngine
{
    internal enum BlockOutcome { Confirmed, Rejected, Unconfirmed }

    internal static BlockOutcome ConfirmBlock(ref IdentityJournal journal, Func<bool> send,
        Func<IdentityPage> inspect, Func<bool> settled, Func<IdentityJournal, bool> persist,
        bool retryOnFailure)
    {
        var outcome = BlockOutcome.Unconfirmed;
        try
        {
            // False means a verified browser precondition rejection: no POST.
            if (!send()) return outcome = BlockOutcome.Rejected;
            // Persist a settled reply before page inspection can wait or crash.
            // Without it, a rejected POST followed by a clear page could remain
            // indistinguishable from an in-flight request after task restart.
            journal = journal with {
                BlockSettled = journal.BlockSettled || settled(),
                RetryBlockAfterRestore = retryOnFailure };
            persist(journal);
            var page = inspect();
            if (page.CorrectAccount && page.CanUnblock && !page.CanBlock)
            {
                journal = journal with { BlockObserved = true };
                outcome = BlockOutcome.Confirmed;
            }
            return outcome;
        }
        finally
        {
            // Keep failure provenance across recovery-task restarts. Observing
            // a late block during compensation must not turn it into a held match.
            journal = journal with {
                BlockSettled = journal.BlockSettled || settled(),
                RetryBlockAfterRestore = retryOnFailure && outcome == BlockOutcome.Unconfirmed };
            persist(journal);
        }
    }

    internal static string RestoredCode(IdentityJournal journal)
        => !journal.RecoveryNeeded && journal.RetryBlockAfterRestore ? "block_unconfirmed" : "";

    internal enum MatchHoldEnd { LeaseExpired, RestoreRequested, GameExited, AccountOffline, Deadline }
    internal static MatchHoldEnd HoldMatch(long started, Func<long> now, Action<int> pump, Action renew,
        Func<bool> authorized, Func<bool> restoreRequested, Func<bool> gameRunning, Func<bool> accountOnline)
    {
        // Transient Steam P2P states cannot prove departure. The UI confirms
        // fresh sustained absence and explicitly requests restoration; the
        // independent owner still handles game/app/account exit and its ceiling.
        while (true)
        {
            if (now() - started >= 4 * 60 * 60 * 1000) return MatchHoldEnd.Deadline;
            if (!authorized()) return MatchHoldEnd.LeaseExpired;
            if (restoreRequested()) return MatchHoldEnd.RestoreRequested;
            if (!gameRunning()) return MatchHoldEnd.GameExited;
            if (!accountOnline()) return MatchHoldEnd.AccountOffline;
            renew();
            pump(500);
        }
    }
    internal static void Hold(long started, Func<long> now, Action<int> pump,
        Func<bool> clientAlive, Func<bool> restoreRequested, Func<bool> peerActive)
    {
        while (now() - started < 8500 && clientAlive() && !restoreRequested() && peerActive()) pump(75);
    }

    internal static bool Attempt(ref IdentityJournal journal, IIdentityRecoveryChannel channel,
        Func<IdentityJournal, bool> persist)
    {
        if (!channel.AccountMatches) throw new InvalidOperationException("原 Steam 账号尚未在线");
        if (!journal.BlockSettled && !journal.BlockObserved)
        {
            var before = channel.Inspect(4000);
            if (before.CorrectAccount && before.CanUnblock && !before.CanBlock)
            { journal = journal with { BlockObserved = true }; persist(journal); }
        }
        var restorationSettled = channel.Restore();
        var page = channel.Inspect();
        if (channel.BlockSettled && !journal.BlockSettled)
        { journal = journal with { BlockSettled = true }; persist(journal); }
        if (page.CorrectAccount && page.CanUnblock && !page.CanBlock && !journal.BlockObserved)
        { journal = journal with { BlockObserved = true }; persist(journal); }
        for (int attempt = 0; channel.Relationship != journal.OriginalRelationship && attempt < 40; attempt++) channel.Wait(50);
        if (!restorationSettled || !CanFinish(journal, channel, page)) return false;
        channel.Wait(750);
        page = channel.Inspect();
        if (!CanFinish(journal, channel, page)) return false;
        // Failed durable completion must leave both the memory and disk pending.
        var completed = journal with { RecoveryNeeded = false };
        if (!persist(completed)) return false;
        journal = completed;
        return true;
    }

    private static bool CanFinish(IdentityJournal journal, IIdentityRecoveryChannel channel, IdentityPage page)
        => channel.AccountMatches && IdentityRules.CanFinish(journal, page.CorrectAccount, page.CanBlock,
            page.CanUnblock, channel.Relationship, page.FriendControl);
}
