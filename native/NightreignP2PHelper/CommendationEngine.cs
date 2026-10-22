namespace NightreignP2PHelper;

internal sealed record CommendationRequest(string Target, string Comment, string ExpectedAccount);
internal sealed record CommendationResult(string State, string Account = "", DateTimeOffset? CooldownUntil = null);

internal interface ICommentPage : IDisposable
{
    bool Inspect();
    string Post(string comment);
}

internal static class CommendationEngine
{
    internal static bool ValidRequest(CommendationRequest? request) => request is not null
        && CommendationHistory.ValidSteamId(request.Target)
        && CommendationHistory.ValidSteamId(request.ExpectedAccount)
        && !string.IsNullOrWhiteSpace(request.Comment) && request.Comment.Length <= 500
        && !request.Comment.Contains('\0') && request.Target != request.ExpectedAccount;

    internal static CommendationResult Send(CommendationRequest request, string account, string root,
        Func<ICommentPage> openPage, Func<DateTimeOffset>? clock = null)
    {
        clock ??= () => DateTimeOffset.UtcNow;
        if (!ValidRequest(request) || request.ExpectedAccount != account)
            return new("error", account);
        CommendationRecord? reservation = null;
        try
        {
            Directory.CreateDirectory(root);
            var stem = Path.Combine(root, account + "-" + request.Target);
            using var targetLock = new FileStream(stem + ".lock", FileMode.OpenOrCreate,
                FileAccess.ReadWrite, FileShare.None);
            var previous = CommendationHistory.Read(stem + ".json", account, request.Target);
            if (CommendationHistory.CoolingDown(previous, clock()))
                return new("cooldown", account, previous!.CooldownUntil);
            using var page = openPage();
            if (!page.Inspect()) return new("precondition", account);
            reservation = CommendationHistory.Reserve(account, request.Target, clock());
            CommendationHistory.Write(stem + ".json", reservation);
            var state = page.Post(request.Comment);
            if (state is not ("sent" or "rejected" or "precondition")) state = "unknown";
            reservation = CommendationHistory.Complete(reservation, state, clock());
            CommendationHistory.Write(stem + ".json", reservation);
            return new(state, account, reservation.CooldownUntil);
        }
        catch
        {
            return new(reservation is null ? "error" : "unknown", account, reservation?.CooldownUntil);
        }
    }
}
