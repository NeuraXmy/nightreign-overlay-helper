// In-memory Steam responses for the production reader; no Steam client or game required.
namespace Steamworks;

internal static class FakeSteam
{
    public static readonly List<ulong> Friends = new();
    public static readonly List<ulong> ServerPlayers = new();
    public static readonly List<ulong> CoplayPlayers = new();
    public static readonly Dictionary<ulong, P2PSessionState_t> Sessions = new();

    public static void Reset()
    {
        Friends.Clear();
        ServerPlayers.Clear();
        CoplayPlayers.Clear();
        Sessions.Clear();
    }

    public static void Connect(ulong id) => Sessions[id] = new() { m_bConnectionActive = 1 };
}

internal enum EFriendFlags { k_EFriendFlagImmediate, k_EFriendFlagOnGameServer }
internal enum ESteamNetworkingConnectionState
{
    k_ESteamNetworkingConnectionState_None,
    k_ESteamNetworkingConnectionState_Connecting,
    k_ESteamNetworkingConnectionState_Connected,
}
internal readonly record struct CSteamID(ulong m_SteamID)
{
    public bool BIndividualAccount() => m_SteamID != 0;
}
internal readonly record struct AppId_t(uint m_AppId);
internal struct SteamNetworkingIdentity
{
    public void SetSteamID(CSteamID id) { }
}
internal struct SteamNetConnectionRealTimeStatus_t
{
    public int m_nPing { get; set; }
    public float m_flConnectionQualityLocal { get; set; }
}
internal struct P2PSessionState_t
{
    public byte m_eP2PSessionError { get; set; }
    public byte m_bConnecting { get; set; }
    public byte m_bConnectionActive { get; set; }
    public uint m_nRemoteIP { get; set; }
    public ushort m_nRemotePort { get; set; }
}
internal static class SteamFriends
{
    private static List<ulong> Players(EFriendFlags flags) =>
        flags == EFriendFlags.k_EFriendFlagImmediate ? FakeSteam.Friends : FakeSteam.ServerPlayers;

    public static int GetFriendCount(EFriendFlags flags) => Players(flags).Count;
    public static CSteamID GetFriendByIndex(int index, EFriendFlags flags) => new(Players(flags)[index]);
    public static int GetCoplayFriendCount() => FakeSteam.CoplayPlayers.Count;
    public static CSteamID GetCoplayFriend(int index) => new(FakeSteam.CoplayPlayers[index]);
    // Reproduce stale/mismatched metadata: it must not hide an active game session.
    public static int GetFriendCoplayTime(CSteamID id) => 1;
    public static AppId_t GetFriendCoplayGame(CSteamID id) => new(123);
    public static string GetFriendPersonaName(CSteamID id) => $"Player {id.m_SteamID}";
}
internal static class SteamUser
{
    public static CSteamID GetSteamID() => new(1);
}
internal static class SteamNetworkingMessages
{
    public static ESteamNetworkingConnectionState GetSessionConnectionInfo(
        ref SteamNetworkingIdentity identity, out int info, out SteamNetConnectionRealTimeStatus_t status)
    {
        info = 0;
        status = default;
        return ESteamNetworkingConnectionState.k_ESteamNetworkingConnectionState_None;
    }
}
internal static class SteamNetworking
{
    public static bool GetP2PSessionState(CSteamID id, out P2PSessionState_t state) =>
        FakeSteam.Sessions.TryGetValue(id.m_SteamID, out state);
}
