namespace NightreignP2PHelper;

internal static class PeerPresencePolicy
{
    internal const long InactivityTimeoutMs = 15_000;
    internal const long PreviousBatchGraceMs = 5_000;
    internal const long RecentPacketMs = 3_000;

    public static bool ShouldKeep(
        EtwPeerMetrics? metrics,
        long nowUnixMs,
        bool isPreviousPeer,
        bool hasNewPeerWithTraffic)
    {
        if (metrics?.LastPacketUnixMs is not long lastPacket)
            return !(isPreviousPeer && hasNewPeerWithTraffic);

        var age = Math.Max(0, nowUnixMs - lastPacket);
        if (age > InactivityTimeoutMs)
            return false;
        if (isPreviousPeer && hasNewPeerWithTraffic && age > PreviousBatchGraceMs)
            return false;
        return true;
    }

    public static bool HasRecentTraffic(EtwPeerMetrics? metrics, long nowUnixMs)
    {
        return metrics?.LastPacketUnixMs is long lastPacket
            && Math.Max(0, nowUnixMs - lastPacket) <= RecentPacketMs;
    }
}
