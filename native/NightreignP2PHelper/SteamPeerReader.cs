using System.Buffers.Binary;
using Steamworks;

namespace NightreignP2PHelper;

internal sealed class SteamPeerReader(EtwPingMonitor? etw = null)
{
    private readonly HashSet<ulong> _lastPublishedPeers = new();
    private readonly SessionCandidateMemory _sessionCandidateMemory = new();

    public IReadOnlyList<PeerSnapshot> ReadPeers()
    {
        var steamFriendsCandidates = GetSteamFriendsCandidates();
        // Recently-played is only a discovery source. Once a real Steam P2P
        // session is confirmed, keep querying it even after Steam's 30-minute
        // coplay timestamp expires. Session state/ETW, rather than that timestamp,
        // decides when a player has actually left this expedition.
        var candidates = _sessionCandidateMemory.BuildCandidates(steamFriendsCandidates);

        var localUser = SteamUser.GetSteamID().m_SteamID;
        var peers = new List<PeerSnapshot>();
        var legacy = new List<LegacyCandidate>();
        var etwTargets = new Dictionary<ulong, ulong>();
        var activeSessionPeers = new HashSet<ulong>();
        foreach (var rawId in candidates.Order())
        {
            if (rawId == 0 || rawId == localUser)
                continue;

            var steamId = new CSteamID(rawId);
            if (!steamId.BIndividualAccount())
                continue;

            var newApiPeer = ReadNewApiPeer(steamId);
            if (newApiPeer is not null)
            {
                activeSessionPeers.Add(rawId);
                peers.Add(newApiPeer);
                continue;
            }

            var legacyPeer = ReadLegacyApiPeer(steamId);
            if (legacyPeer is null)
                continue;
            activeSessionPeers.Add(rawId);
            legacy.Add(legacyPeer);
            etwTargets[rawId] = legacyPeer.NetworkIdentity;
        }

        _sessionCandidateMemory.UpdateActiveSessions(activeSessionPeers);

        etw?.SyncTargets(etwTargets);
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var etwReady = etw is not null;
        var hasNewPeerWithTraffic = etwReady && legacy.Any(candidate =>
            !_lastPublishedPeers.Contains(candidate.SteamId.m_SteamID)
            && PeerPresencePolicy.HasRecentTraffic(etw?.GetMetrics(candidate.SteamId.m_SteamID), now));

        foreach (var candidate in legacy)
        {
            var rawId = candidate.SteamId.m_SteamID;
            var metrics = etwReady ? etw?.GetMetrics(rawId) : null;
            if (etwReady && !PeerPresencePolicy.ShouldKeep(
                    metrics,
                    now,
                    _lastPublishedPeers.Contains(rawId),
                    hasNewPeerWithTraffic))
                continue;

            peers.Add(new PeerSnapshot(
                rawId.ToString(),
                GetName(candidate.SteamId),
                metrics?.PingMs,
                metrics?.Quality,
                "legacy",
                candidate.Connected ? "connected" : "connecting"));
        }

        _lastPublishedPeers.Clear();
        _lastPublishedPeers.UnionWith(peers.Select(peer => ulong.Parse(peer.SteamId)));
        return peers;
    }

    private static HashSet<ulong> GetSteamFriendsCandidates()
    {
        var candidates = new HashSet<ulong>();
        const EFriendFlags flags = EFriendFlags.k_EFriendFlagOnGameServer;

        var serverCount = SteamFriends.GetFriendCount(flags);
        for (var i = 0; i < Math.Max(0, serverCount); i++)
        {
            var id = SteamFriends.GetFriendByIndex(i, flags);
            if (id.m_SteamID != 0)
                candidates.Add(id.m_SteamID);
        }

        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var coplayCount = SteamFriends.GetCoplayFriendCount();
        for (var i = 0; i < Math.Max(0, coplayCount); i++)
        {
            var id = SteamFriends.GetCoplayFriend(i);
            if (id.m_SteamID == 0)
                continue;

            var playedAt = SteamFriends.GetFriendCoplayTime(id);
            if (CandidatePolicy.IsRecentNightreign(
                SteamFriends.GetFriendCoplayGame(id).m_AppId,
                playedAt,
                now))
                candidates.Add(id.m_SteamID);
        }

        return candidates;
    }

    private static PeerSnapshot? ReadNewApiPeer(CSteamID steamId)
    {
        var identity = new SteamNetworkingIdentity();
        identity.SetSteamID(steamId);
        var state = SteamNetworkingMessages.GetSessionConnectionInfo(
            ref identity,
            out _,
            out var realTimeStatus);

        if (state is not (ESteamNetworkingConnectionState.k_ESteamNetworkingConnectionState_Connecting
            or ESteamNetworkingConnectionState.k_ESteamNetworkingConnectionState_Connected))
            return null;

        int? ping = realTimeStatus.m_nPing >= 0 ? realTimeStatus.m_nPing : null;
        double? quality = realTimeStatus.m_flConnectionQualityLocal is >= 0 and <= 1
            ? realTimeStatus.m_flConnectionQualityLocal
            : null;

        return new PeerSnapshot(
            steamId.m_SteamID.ToString(),
            GetName(steamId),
            ping,
            quality,
            "messages",
            state == ESteamNetworkingConnectionState.k_ESteamNetworkingConnectionState_Connected ? "connected" : "connecting");
    }

    private static LegacyCandidate? ReadLegacyApiPeer(CSteamID steamId)
    {
        if (!SteamNetworking.GetP2PSessionState(steamId, out var session))
            return null;
        if (session.m_eP2PSessionError != 0 || (session.m_bConnecting == 0 && session.m_bConnectionActive == 0))
            return null;

        return new LegacyCandidate(
            steamId,
            BuildNetworkIdentity(session.m_nRemoteIP, session.m_nRemotePort),
            session.m_bConnectionActive != 0);
    }

    internal static ulong BuildNetworkIdentity(uint remoteIp, ushort remotePort)
    {
        var ipv4 = BinaryPrimitives.ReverseEndianness(remoteIp);
        return ((ulong)remotePort << 32) | ipv4;
    }

    private static string GetName(CSteamID steamId)
    {
        var name = SteamFriends.GetFriendPersonaName(steamId);
        return string.IsNullOrWhiteSpace(name) || name.Equals("[unknown]", StringComparison.OrdinalIgnoreCase)
            ? "未知玩家"
            : name;
    }

    private sealed record LegacyCandidate(CSteamID SteamId, ulong NetworkIdentity, bool Connected);
}
