using NightreignP2PHelper;
using Steamworks;

var cases = new (string Name, Action Run)[]
{
    ("Invited friend without server or coplay entries", () =>
    {
        FakeSteam.Friends.AddRange([1, 2, 3]);
        FakeSteam.Connect(2);
        ExpectPeers(new SteamPeerReader(), 2);
    }),
    ("Active non-friend with stale coplay metadata", () =>
    {
        FakeSteam.CoplayPlayers.AddRange([2, 3]);
        FakeSteam.Connect(2);
        ExpectPeers(new SteamPeerReader(), 2);
    }),
    ("Candidates require an actual connection and are deduplicated", () =>
    {
        FakeSteam.Friends.AddRange([0, 1, 2, 3, 4, 5]);
        FakeSteam.ServerPlayers.Add(2);
        FakeSteam.CoplayPlayers.Add(2);
        FakeSteam.Connect(2);
        FakeSteam.Sessions[4] = new() { m_bConnectionActive = 1, m_eP2PSessionError = 1 };
        FakeSteam.Sessions[5] = new();
        ExpectPeers(new SteamPeerReader(), 2);
    }),
    ("Session survives discovery disappearance and is removed on disconnect", () =>
    {
        var reader = new SteamPeerReader();
        FakeSteam.ServerPlayers.Add(2);
        FakeSteam.Connect(2);
        ExpectPeers(reader, 2);
        FakeSteam.ServerPlayers.Clear();
        ExpectPeers(reader, 2);
        FakeSteam.Sessions.Clear();
        ExpectPeers(reader);
    }),
    ("ETW without metrics still shows a connected friend", () =>
    {
        FakeSteam.Friends.Add(2);
        FakeSteam.Connect(2);
        ExpectPeers(new SteamPeerReader(new EtwPingMonitor()), 2);
    }),
    ("Snapshots expose actual friend relationships for both connected peers", () =>
    {
        FakeSteam.Friends.Add(2);
        FakeSteam.CoplayPlayers.Add(3);
        FakeSteam.Connect(2);
        FakeSteam.Connect(3);
        var peers = new SteamPeerReader().ReadPeers();
        if (peers.Single(p => p.SteamId == "2").Relationship != 3
            || peers.Single(p => p.SteamId == "3").Relationship != 0)
            throw new Exception("Friend relationship was lost.");
    }),
};

var failures = 0;
foreach (var (name, run) in cases.Concat(CommendationTests.Cases))
{
    FakeSteam.Reset();
    try
    {
        run();
        Console.WriteLine($"PASS {name}");
    }
    catch (Exception ex)
    {
        failures++;
        Console.Error.WriteLine($"FAIL {name}: {ex.Message}");
    }
}
return failures == 0 ? 0 : 1;

static void ExpectPeers(SteamPeerReader reader, params ulong[] expected)
{
    var actual = reader.ReadPeers().Select(peer => ulong.Parse(peer.SteamId)).Order().ToArray();
    if (!actual.SequenceEqual(expected.Order()))
        throw new Exception($"Expected [{string.Join(',', expected)}], got [{string.Join(',', actual)}]");
}

namespace NightreignP2PHelper
{
    // Keep the test independent of Windows ETW and exercise the reader's no-metrics path.
    internal sealed class EtwPingMonitor
    {
        public void SyncTargets(IReadOnlyDictionary<ulong, ulong> targets) { }
        public EtwPeerMetrics? GetMetrics(ulong steamId) => null;
    }
}
