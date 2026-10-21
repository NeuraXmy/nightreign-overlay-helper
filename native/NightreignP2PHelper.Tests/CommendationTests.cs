using NightreignP2PHelper;

internal static class CommendationTests
{
    private const string Account = "76561198000000001", Target = "76561198000000002";
    private static readonly DateTimeOffset Start = new(2026, 10, 20, 1, 0, 0, TimeSpan.Zero);
    internal static IEnumerable<(string Name, Action Run)> Cases => new (string, Action)[]
    {
        ("Comment request pins account and target", () => {
            using var test = new Scenario();
            foreach (var request in new[] {
                new CommendationRequest(Target, "ok", ""), new(Account, "ok", Account),
                new(Target, "", Account), new(Target, "a\0b", Account),
                new("../../fake", "ok", Account), new(Target, new string('a', 501), Account) })
                Check(test.Send(request).State == "error");
            Check(test.Page.Posts == 0 && test.Page.Inspections == 0);
            Check(!CommendationHistory.ValidSteamId("７６５６１１９８００００００００２"));
        }),
        ("Comment is reserved before POST and blocked for seven days", () => {
            using var test = new Scenario();
            test.Page.BeforePost = () => Check(CommendationHistory.Read(test.Path, Account, Target)?.State == "sending");
            Check(test.Send().State == "sent");
            Check(test.Send().State == "cooldown");
            Check(test.Page.Posts == 1);
            test.Now = Start.AddDays(7);
            Check(test.Send().State == "sent" && test.Page.Posts == 2);
        }),
        ("Unknown or interrupted POST keeps durable reservation", () => {
            using var test = new Scenario();
            test.Page.BeforePost = () => throw new IOException("connection lost after POST");
            Check(test.Send().State == "unknown");
            Check(test.Send().State == "cooldown" && test.Page.Posts == 1);
            Check(CommendationHistory.Read(test.Path, Account, Target)?.CooldownUntil == Start.AddDays(7));
        }),
        ("Rejected comment only permits an explicit later retry", () => {
            using var test = new Scenario();
            test.Page.Outcome = "rejected";
            Check(test.Send().State == "rejected");
            Check(test.Send().State == "cooldown" && test.Page.Posts == 1);
            test.Now = Start.AddSeconds(61);
            Check(test.Send().State == "rejected" && test.Page.Posts == 2);
        }),
        ("Unavailable comments do not POST or reserve", () => {
            using var test = new Scenario();
            test.Page.Ready = false;
            Check(test.Send().State == "precondition");
            Check(!File.Exists(test.Path) && test.Page.Posts == 0);
        }),
        ("Corrupt and mismatched history fail closed", () => {
            using var test = new Scenario();
            foreach (var text in new[] {"{", "null", "{}"}) {
                File.WriteAllText(test.Path, text);
                Check(test.Send().State == "error");
            }
            CommendationHistory.Write(test.Path, CommendationHistory.Reserve(Target, Account, Start));
            Check(test.Send().State == "error" && test.Page.Posts == 0);
        }),
        ("Concurrent helper is excluded by account-target lock", () => {
            using var test = new Scenario();
            using var locked = new FileStream(System.IO.Path.ChangeExtension(test.Path, ".lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            Check(test.Send().State == "error" && test.Page.Posts == 0);
        }),
        ("Journal write failure prevents external POST", () => {
            using var test = new Scenario();
            Directory.CreateDirectory(test.Path);
            Check(test.Send().State == "unknown" && test.Page.Posts == 0);
        }),
        ("Account switch cannot use previous account's roster", () => {
            using var test = new Scenario();
            Check(test.Send(new(Target, "ok", "76561198000000003")).State == "error");
            Check(test.Page.Inspections == 0);
        }),
    };

    private static void Check(bool condition)
    {
        if (!condition) throw new Exception("Commendation assertion failed");
    }

    private sealed class Page : ICommentPage
    {
        internal bool Ready = true;
        internal string Outcome = "sent";
        internal int Posts, Inspections;
        internal Action? BeforePost;
        public bool Inspect() { Inspections++; return Ready; }
        public string Post(string comment) { Posts++; BeforePost?.Invoke(); return Outcome; }
        public void Dispose() { }
    }

    private sealed class Scenario : IDisposable
    {
        internal readonly string Root = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "nr-commendation-tests-" + Guid.NewGuid().ToString("N"));
        internal string Path => System.IO.Path.Combine(Root, Account + "-" + Target + ".json");
        internal DateTimeOffset Now = Start;
        internal readonly Page Page = new();
        internal Scenario() => Directory.CreateDirectory(Root);
        internal CommendationResult Send(CommendationRequest? request = null) => CommendationEngine.Send(
            request ?? new(Target, "great teammate", Account), Account, Root, () => Page, () => Now);
        public void Dispose()
        {
            var target = System.IO.Path.GetFullPath(Root);
            var temp = System.IO.Path.GetFullPath(System.IO.Path.GetTempPath());
            if (!target.StartsWith(temp, StringComparison.OrdinalIgnoreCase)
                || !System.IO.Path.GetFileName(target).StartsWith("nr-commendation-tests-")) throw new IOException();
            Directory.Delete(target, recursive: true);
        }
    }
}
