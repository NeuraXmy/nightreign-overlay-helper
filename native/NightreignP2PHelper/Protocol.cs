using System.Text.Json;
using System.Text.Json.Serialization;

namespace NightreignP2PHelper;

internal sealed record PeerSnapshot(
    [property: JsonPropertyName("steam_id")] string SteamId,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("ping_ms")] int? PingMs,
    [property: JsonPropertyName("quality")] double? Quality,
    [property: JsonPropertyName("api")] string Api,
    [property: JsonPropertyName("state")] string State);

internal static class Protocol
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
    };

    private static readonly object WriteLock = new();
    private static string? _lastStatusKey;
    private static string _etwState = "disabled";

    public static string EtwState => _etwState;

    public static void SetEtwState(string state)
    {
        _etwState = state;
    }

    public static void Status(string state, string message, bool force = false)
    {
        var key = $"{state}\n{message}\n{_etwState}";
        if (!force && key == _lastStatusKey)
            return;

        _lastStatusKey = key;
        Write(new { type = "status", state, message, etw_state = _etwState });
    }

    public static void Snapshot(IReadOnlyCollection<PeerSnapshot> peers)
    {
        Write(new { type = "snapshot", peers });
    }

    internal static string Serialize<T>(T payload) => JsonSerializer.Serialize(payload, Options);

    public static void LogError(string message)
    {
        Console.Error.WriteLine(message);
        Console.Error.Flush();
    }

    private static void Write<T>(T payload)
    {
        lock (WriteLock)
        {
            Console.Out.WriteLine(Serialize(payload));
            Console.Out.Flush();
        }
    }
}
