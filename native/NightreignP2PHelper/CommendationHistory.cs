using System.Text.Json;
using System.Runtime.InteropServices;

namespace NightreignP2PHelper;

internal sealed record CommendationRecord(string Account, string Target, string State,
    DateTimeOffset AttemptedAt, DateTimeOffset CooldownUntil);

internal static class CommendationHistory
{
    internal static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true
    };

    internal static bool ValidSteamId(string? value) => value is { Length: 17 }
        && value.All(c => c is >= '0' and <= '9')
        && ulong.TryParse(value, out var id) && id >= 76561197960265728UL && id <= 76561202255233023UL;

    internal static bool CoolingDown(CommendationRecord? previous, DateTimeOffset now)
        => previous is not null && previous.CooldownUntil > now;

    // Reserve durably BEFORE the sole POST. Crash/timeout keeps the seven-day fence.
    internal static CommendationRecord Reserve(string account, string target, DateTimeOffset now)
        => new(account, target, "sending", now, now.AddDays(7));

    internal static CommendationRecord Complete(CommendationRecord record, string result, DateTimeOffset now)
        => record with { State = result, CooldownUntil = result is "rejected" or "precondition"
            ? now.AddSeconds(60) : record.CooldownUntil };

    internal static CommendationRecord? Read(string path, string account, string target)
    {
        if (!File.Exists(path)) return null;
        var value = JsonSerializer.Deserialize<CommendationRecord>(File.ReadAllText(path), Json);
        if (value is null || value.Account != account || value.Target != target
            || value.State is not ("sending" or "sent" or "unknown" or "rejected" or "precondition")
            || value.AttemptedAt == default || value.CooldownUntil < value.AttemptedAt)
            throw new InvalidDataException("Invalid commendation history");
        return value;
    }

    internal static void Write(string path, CommendationRecord record)
    {
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write,
                FileShare.None, 4096, FileOptions.WriteThrough))
            {
                JsonSerializer.Serialize(stream, record, Json);
                stream.Flush(flushToDisk: true);
            }
            if (OperatingSystem.IsWindows())
            {
                if (!MoveFileEx(temporary, path, 0x1 | 0x8)) throw new IOException("Could not commit commendation history");
            }
            else File.Move(temporary, path, overwrite: true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool MoveFileEx(string existing, string destination, int flags);
}
