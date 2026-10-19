namespace NightreignP2PHelper;

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
