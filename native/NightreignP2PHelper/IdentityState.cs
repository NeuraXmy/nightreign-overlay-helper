using System.Text.Json;

namespace NightreignP2PHelper;

internal sealed record IdentityRequest(string Transaction, string Target, string Client, DateTimeOffset CreatedAt,
    string ExpectedAccount = "");
internal sealed record IdentityPage(bool CorrectAccount, bool CanBlock, bool CanUnblock, bool FriendControl);
internal sealed record IdentityJournal(
    string Account, string Target, string Transaction, int OriginalRelationship,
    bool BlockSettled, bool BlockObserved, bool RecoveryNeeded, DateTimeOffset CreatedAt,
    bool RetryBlockAfterRestore = false, int RecoveryAttempts = 0, bool RecoveryStopped = false);

// Reserve attempts durably before Steam initialization or dispatch. A crash consumes
// the reserved attempt too; stopped journals remain evidence, never completion.
internal static class IdentityRecoveryBudget
{
    internal const int Limit = 3;
    internal static IdentityJournal Reserve(string path, IdentityJournal journal)
    {
        if (journal.RecoveryStopped || journal.RecoveryAttempts >= Limit)
            throw new InvalidOperationException("Recovery limit reached");
        var reserved = journal with { RecoveryAttempts = journal.RecoveryAttempts + 1 };
        IdentityFiles.Write(path, reserved);
        return reserved;
    }

    internal static bool StopExhausted(string path, IdentityJournal journal)
    {
        if (!journal.RecoveryNeeded || journal.RecoveryAttempts < Limit) return journal.RecoveryStopped;
        var stopped = journal with { RecoveryStopped = true };
        var root = Path.GetDirectoryName(path)!;
        // Keep a transaction-specific tombstone even when this account's journal
        // is later replaced by a new match. It also carries offline notifications.
        var tombstone = Path.Combine(root, "recovery-stopped-" + journal.Transaction + ".json");
        if (!File.Exists(tombstone)) IdentityFiles.Write(tombstone, stopped);
        if (!journal.RecoveryStopped) IdentityFiles.Write(path, stopped);
        var claimPath = Path.Combine(root, "active-request.json");
        var claim = IdentityFiles.Read<IdentityRequest>(claimPath);
        if (claim?.Transaction == journal.Transaction) File.Delete(claimPath);
        File.Delete(Path.Combine(root, "requests", journal.Transaction + ".json"));
        return true;
    }
}

internal static class IdentityRules
{
    internal static bool ValidSteamId(string? value) => value is { Length: 17 }
        && value.All(c => c is >= '0' and <= '9')
        && ulong.TryParse(value, out var id) && id >= 76561197960265728UL && id <= 76561202255233023UL;
    internal static bool CanBegin(int relationship, bool correctAccount, bool canBlock, bool canUnblock)
        => (relationship is 0 or 3) && correctAccount && canBlock && !canUnblock;
    // An unblocked snapshot is insufficient when the original POST might still arrive.
    internal static bool CanFinish(IdentityJournal journal, bool correctAccount, bool canBlock,
        bool canUnblock, int relationship, bool friendControl) => journal.RecoveryNeeded
        && (journal.BlockSettled || journal.BlockObserved) && correctAccount && canBlock && !canUnblock
        && (relationship == journal.OriginalRelationship
            || journal.OriginalRelationship == 0 && relationship == 3 && friendControl)
        && (relationship != 3 || friendControl);
}

internal static class IdentityFiles
{
    internal static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true
    };
    internal static string Root => Environment.GetEnvironmentVariable("NROH_IDENTITY_DIR")
        ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "NightreignOverlayHelper", "identity");

    internal static T? Read<T>(string path)
    {
        if (!File.Exists(path)) return default;
        if (new FileInfo(path).Length > 65536) throw new InvalidDataException("Recovery record is too large.");
        return JsonSerializer.Deserialize<T>(File.ReadAllText(path), Json);
    }

    internal static void Write<T>(string path, T value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                4096, FileOptions.WriteThrough))
            {
                JsonSerializer.Serialize(stream, value, Json);
                stream.Flush(flushToDisk: true);
            }
            // Windows rename with WRITE_THROUGH makes the replacement durable as well.
            if (OperatingSystem.IsWindows())
            {
                if (!MoveFileEx(temporary, path, 0x1 | 0x8))
                    throw new IOException("Identity state could not be committed.");
            }
            else File.Move(temporary, path, overwrite: true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode, SetLastError = true)]
    [return: System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.Bool)]
    private static extern bool MoveFileEx(string existing, string destination, int flags);
}
