namespace NightreignP2PHelper;

internal static class CandidatePolicy
{
    internal const uint NightreignAppId = 2622380;
    internal const long RecentPlayerWindowSeconds = 30 * 60;

    public static bool IsRecentNightreign(uint appId, long playedAt, long now)
    {
        if (appId != NightreignAppId || playedAt <= 0)
            return false;
        var age = now - playedAt;
        return age is >= 0 and <= RecentPlayerWindowSeconds;
    }
}

internal sealed class SessionCandidateMemory
{
    private readonly HashSet<ulong> _activeSessionPeers = new();

    public HashSet<ulong> BuildCandidates(IReadOnlyCollection<ulong> discoveredPeers)
    {
        var candidates = new HashSet<ulong>(_activeSessionPeers);
        candidates.UnionWith(discoveredPeers);
        return candidates;
    }

    public void UpdateActiveSessions(IEnumerable<ulong> activeSessionPeers)
    {
        _activeSessionPeers.Clear();
        _activeSessionPeers.UnionWith(activeSessionPeers);
    }

    internal IReadOnlyCollection<ulong> ActiveSessionPeers => _activeSessionPeers;
}
