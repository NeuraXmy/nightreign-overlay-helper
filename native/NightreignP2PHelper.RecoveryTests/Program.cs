using NightreignP2PHelper;
using System.Diagnostics;

// No Steam SDK or account calls: exercise the production recovery driver with
// injected transport, storage failures, a fake clock, and a real child restart.
internal static class Program
{
    private const string Account = "76561198049468922", Target = "76561198049468923";
    private static readonly IdentityPage Clear = new(true, true, false, true);
    private static readonly IdentityPage Blocked = new(true, false, true, true);
    private static int passed;
    private static IdentityJournal Pending(bool settled = true, bool observed = true)
        => new(Account, Target, Guid.NewGuid().ToString("N"), 3, settled, observed, true, DateTimeOffset.UtcNow);
    private static void Assert(bool value, string message)
    { if (!value) throw new Exception(message); }
    private static void Test(string name, Action test)
    { test(); passed++; Console.WriteLine("PASS " + name); }

    private static int Main(string[] args)
    {
        if (args.Length == 2 && args[0] == "--recover-journal")
        {
            var loaded = IdentityFiles.Read<IdentityJournal>(args[1]) ?? throw new Exception("missing journal");
            return IdentityRecoveryEngine.Attempt(ref loaded, new FakeChannel(), x => { IdentityFiles.Write(args[1], x); return true; }) ? 0 : 1;
        }
        if (args.Length == 3 && args[0] == "--supervisor-test-task")
            return IdentitySupervisorTests.TaskChild(args[1], int.Parse(args[2]));
        Test("restore verifies twice and commits completion", () => {
            var journal = Pending(); var channel = new FakeChannel(); IdentityJournal? saved = null;
            Assert(IdentityRecoveryEngine.Attempt(ref journal, channel, x => { saved = x; return true; }), "not restored");
            Assert(!journal.RecoveryNeeded && saved == journal && channel.Inspections == 2, "missing verification/commit");
        });
        Test("network failure retains pending then next attempt succeeds", () => {
            var journal = Pending(); var channel = new FakeChannel { RestoreFailure = true }; var writes = 0;
            try { IdentityRecoveryEngine.Attempt(ref journal, channel, _ => { writes++; return true; }); throw new Exception("expected network error"); }
            catch (IOException) { }
            Assert(journal.RecoveryNeeded && writes == 0, "failure discarded pending");
            channel.RestoreFailure = false;
            Assert(IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true), "retry failed");
        });
        Test("unknown original block cannot be declared restored from clear page", () => {
            var journal = Pending(false, false); var channel = new FakeChannel { BlockSettled = false };
            Assert(!IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true) && journal.RecoveryNeeded, "ambiguous request cleared");
            Assert(channel.Restores == 1, "compensation skipped");
        });
        Test("observed blocked state resolves original uncertainty", () => {
            var journal = Pending(false, false); var channel = new FakeChannel { BlockSettled = false };
            channel.Pages.Enqueue(Blocked);
            Assert(IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true) && journal.BlockObserved, "observation lost");
        });
        Test("unknown restore result never clears journal", () => {
            var journal = Pending(); var channel = new FakeChannel { RestoreSettled = false };
            Assert(!IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true) && journal.RecoveryNeeded, "in-flight restore discarded");
        });
        Test("wrong account sends no restoration", () => {
            var journal = Pending(); var channel = new FakeChannel { AccountMatches = false };
            try { IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true); throw new Exception("expected mismatch"); }
            catch (InvalidOperationException) { }
            Assert(channel.Restores == 0 && journal.RecoveryNeeded, "wrong account modified");
        });
        Test("relationship and friend control must both match", () => {
            var journal = Pending(); var channel = new FakeChannel { Relationship = 6 };
            Assert(!IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true), "wrong relationship accepted");
            channel.Relationship = 3; channel.Pages.Enqueue(Clear with { FriendControl = false });
            Assert(!IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true), "lost friendship accepted");
        });
        Test("second observation catches block returning", () => {
            var journal = Pending(); var channel = new FakeChannel(); channel.Pages.Enqueue(Clear); channel.Pages.Enqueue(Blocked);
            Assert(!IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true) && journal.RecoveryNeeded, "late block missed");
        });
        Test("storage failures after block never skip compensation", () => {
            var journal = Pending(false, false); var channel = new FakeChannel { BlockSettled = false }; channel.Pages.Enqueue(Blocked);
            Assert(!IdentityRecoveryEngine.Attempt(ref journal, channel, _ => false), "failed commit reported complete");
            Assert(journal.RecoveryNeeded && journal.BlockObserved && channel.Restores == 1, "lost memory evidence or skipped recovery");
            Assert(IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true), "storage recovery failed");
        });
        Test("unconfirmed block retries only after verified durable restoration", () => {
            var journal = Pending(false, false); IdentityJournal? saved = null;
            var outcome = IdentityRecoveryEngine.ConfirmBlock(ref journal, () => true, () => {
                Assert(saved is { BlockSettled: true, RecoveryNeeded: true, RetryBlockAfterRestore: true },
                    "settled reply not durable before page inspection");
                return Clear;
            },
                () => true, x => { saved = x; return true; }, retryOnFailure: true);
            Assert(outcome == IdentityRecoveryEngine.BlockOutcome.Unconfirmed && saved == journal
                && journal.RetryBlockAfterRestore, "failed attempt not recorded");
            Assert(IdentityRecoveryEngine.RestoredCode(journal) == "", "retry before compensation");
            var channel = new FakeChannel { RestoreFailure = true };
            try { IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true); throw new Exception("expected network error"); }
            catch (IOException) { }
            Assert(IdentityRecoveryEngine.RestoredCode(journal) == "", "network error authorized retry");
            channel.RestoreFailure = false;
            Assert(!IdentityRecoveryEngine.Attempt(ref journal, channel, _ => false), "failed commit accepted");
            Assert(IdentityRecoveryEngine.RestoredCode(journal) == "", "disk error authorized retry");
            Assert(IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true), "recovery failed");
            Assert(IdentityRecoveryEngine.RestoredCode(journal) == "block_unconfirmed", "safe retry lost");
        });
        foreach (var stage in new[] { "post", "inspect" })
            Test(stage + " timeout preserves retry provenance for compensation", () => {
                var journal = Pending(false, false); IdentityJournal? saved = null;
                try
                {
                    IdentityRecoveryEngine.ConfirmBlock(ref journal,
                        () => stage == "post" ? throw new TimeoutException() : true,
                        () => throw new TimeoutException(), () => false,
                        x => { saved = x; return true; }, retryOnFailure: true);
                    throw new Exception("expected timeout");
                }
                catch (TimeoutException) { }
                Assert(saved == journal && journal.RecoveryNeeded && journal.RetryBlockAfterRestore,
                    "timeout lost durable recovery intent");
                var channel = new FakeChannel { BlockSettled = false };
                Assert(!IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true), "ambiguous POST cleared");
                Assert(IdentityRecoveryEngine.RestoredCode(journal) == "", "unknown POST retried early");
                channel.Pages.Enqueue(Blocked); // Late original POST observed by the recovery task.
                Assert(IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true), "late block recovery failed");
                Assert(journal.BlockObserved && IdentityRecoveryEngine.RestoredCode(journal) == "block_unconfirmed",
                    "compensation observation erased failed attempt");
            });
        Test("confirmed hold and rejected precondition do not request another block", () => {
            foreach (var accepted in new[] { true, false })
            {
                var journal = Pending(false, false); var inspections = 0;
                var outcome = IdentityRecoveryEngine.ConfirmBlock(ref journal, () => accepted,
                    () => { inspections++; return Blocked; }, () => true, _ => true, retryOnFailure: true);
                Assert(outcome == (accepted ? IdentityRecoveryEngine.BlockOutcome.Confirmed
                    : IdentityRecoveryEngine.BlockOutcome.Rejected), "wrong block outcome");
                Assert(inspections == (accepted ? 1 : 0) && !journal.RetryBlockAfterRestore,
                    "precondition or successful hold armed retry");
                Assert(IdentityRecoveryEngine.Attempt(ref journal, new FakeChannel(), _ => true), "recovery failed");
                Assert(IdentityRecoveryEngine.RestoredCode(journal) == "", "normal restore reblocked");
            }
        });
        Test("legacy identity probe never opts into match block retry", () => {
            var journal = Pending(false, false);
            IdentityRecoveryEngine.ConfirmBlock(ref journal, () => true, () => Clear, () => true,
                _ => true, retryOnFailure: false);
            Assert(IdentityRecoveryEngine.Attempt(ref journal, new FakeChannel(), _ => true), "recovery failed");
            Assert(IdentityRecoveryEngine.RestoredCode(journal) == "", "legacy probe armed match retry");
        });
        Test("older journals without retry metadata remain recoverable without reblocking", () => {
            var data = System.Text.Json.JsonSerializer.Serialize(Pending(), IdentityFiles.Json);
            var old = System.Text.Json.Nodes.JsonNode.Parse(data)!.AsObject();
            old.Remove("retry_block_after_restore");
            var journal = System.Text.Json.JsonSerializer.Deserialize<IdentityJournal>(old.ToJsonString(), IdentityFiles.Json)!;
            Assert(!journal.RetryBlockAfterRestore, "old journal opted in");
            Assert(IdentityRecoveryEngine.Attempt(ref journal, new FakeChannel(), _ => true), "old journal cannot recover");
            Assert(IdentityRecoveryEngine.RestoredCode(journal) == "", "old journal reblocked");
        });
        Test("app death, early stop, peer departure and deadline end hold", () => {
            foreach (var cause in new[] { "app", "stop", "peer", "deadline" })
            {
                long now = 0;
                IdentityRecoveryEngine.Hold(0, () => now, duration => now += duration,
                    () => cause != "app" || now < 300, () => cause == "stop" && now >= 300,
                    () => cause != "peer" || now < 300);
                Assert(cause == "deadline" ? now >= 8500 && now < 8600 : now == 300, "hold outlived " + cause);
            }
        });
        Test("preexisting blocks and ambiguous state cannot begin", () => {
            foreach (var relation in new[] { 1, 2, 4, 5, 6 }) Assert(!IdentityRules.CanBegin(relation, true, true, false), "bad original relation");
            Assert(!IdentityRules.CanBegin(3, true, false, true), "web block ignored");
            Assert(!IdentityRules.CanBegin(3, true, true, true), "ambiguous controls ignored");
            Assert(!IdentityRules.CanBegin(0, false, true, false), "wrong actor ignored");
        });
        Test("new process consumes durable pending journal without Steam", () => {
            var root = Path.Combine(Path.GetTempPath(), "nr-identity-test-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
            try
            {
                var path = Path.Combine(root, "journal.json"); var journal = Pending(false, false);
                IdentityRecoveryEngine.ConfirmBlock(ref journal, () => true, () => Clear, () => true,
                    x => { IdentityFiles.Write(path, x); return true; }, retryOnFailure: true);
                Assert(IdentityFiles.Read<IdentityJournal>(path) == journal, "journal round trip failed");
                var start = new ProcessStartInfo("dotnet") { UseShellExecute = false, CreateNoWindow = true };
                start.ArgumentList.Add(typeof(Program).Assembly.Location); start.ArgumentList.Add("--recover-journal"); start.ArgumentList.Add(path);
                using var child = Process.Start(start) ?? throw new Exception("child failed");
                Assert(child.WaitForExit(15000) && child.ExitCode == 0, "restart recovery failed");
                var finished = IdentityFiles.Read<IdentityJournal>(path)!;
                Assert(!finished.RecoveryNeeded && finished.Transaction == journal.Transaction, "wrong journal consumed");
                Assert(IdentityRecoveryEngine.RestoredCode(finished) == "block_unconfirmed", "restart lost retry outcome");
            }
            finally { Directory.Delete(root, recursive: true); }
        });
        Test("match hold survives more than nine seconds and renews browser watchdog", () => {
            long now = 0; int renewals = 0;
            IdentityRecoveryEngine.HoldMatch(0, () => now, ms => now += ms, () => renewals++,
                () => now < 60000, () => false, () => true, () => true);
            Assert(now == 60000 && renewals == 120, "match hold expired like the old probe");
        });
        Test("match hold restores on parent death, stop, game exit and account offline", () => {
            foreach (var cause in new[] { "app", "stop", "game", "account" })
            {
                long now = 0;
                var end = IdentityRecoveryEngine.HoldMatch(0, () => now, ms => now += ms, () => {},
                    () => cause != "app" || now < 1000, () => cause == "stop" && now >= 1000,
                    () => cause != "game" || now < 1000, () => cause != "account" || now < 1000);
                Assert(now == 1000, "hold outlived " + cause);
                var expected = cause switch {
                    "app" => IdentityRecoveryEngine.MatchHoldEnd.LeaseExpired,
                    "stop" => IdentityRecoveryEngine.MatchHoldEnd.RestoreRequested,
                    "game" => IdentityRecoveryEngine.MatchHoldEnd.GameExited,
                    _ => IdentityRecoveryEngine.MatchHoldEnd.AccountOffline };
                Assert(end == expected, "wrong end reason " + cause);
            }
        });
        Test("match hold has independent four-hour ceiling", () => {
            long now = 4 * 60 * 60 * 1000 - 500;
            IdentityRecoveryEngine.HoldMatch(0, () => now, ms => now += ms, () => {},
                () => true, () => false, () => true, () => true);
            Assert(now == 4 * 60 * 60 * 1000, "ceiling ignored");
        });
        Test("nonfriend recovery requires original nonfriend state", () => {
            var journal = Pending() with { OriginalRelationship = 0 };
            var channel = new FakeChannel { Relationship = 0 };
            Assert(IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true), "nonfriend not restored");
        });
        Test("friend added during hold is preserved after verified unblock", () => {
            var journal = Pending() with { OriginalRelationship = 0 };
            Assert(IdentityRecoveryEngine.Attempt(ref journal, new FakeChannel { Relationship = 3 }, _ => true),
                "new friendship kept recovery pending forever");
        });
        Test("stuck task has a finite supervisor deadline while healthy long holds survive", () => {
            Assert(!IdentitySupervisor.TaskExpired(120_000, 1000), "early stall timeout");
            Assert(IdentitySupervisor.TaskExpired(121_000, 1000), "stalled task survives");
            Assert(!IdentitySupervisor.TaskExpired(3 * 60 * 60_000, 3 * 60 * 60_000), "healthy hold killed");
            Assert(IdentitySupervisor.TaskExpired(250 * 60_000, 250 * 60_000), "absolute task ceiling missing");
        });
        Test("invalid Steam IDs and future client leases cannot authorize work", () => {
            foreach (var invalid in new string?[] { null, "", "7656119804946892 ", "+6561198049468922",
                "７６５６１１９８０４９４６８９２２", "76561197960265727" })
                Assert(!IdentityRules.ValidSteamId(invalid), "invalid identity accepted");
            var now = DateTimeOffset.UtcNow;
            Assert(!IdentityRecoveryHandoff.FreshClient(now.AddSeconds(6), now), "future lease kept hold alive");
        });
        Test("restoring one teammate does not clear the other durable journal", () => {
            var root = Path.Combine(Path.GetTempPath(), "nr-match-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                var first = Pending(); var second = Pending() with { Target = "76561198049468924" };
                var path1 = Path.Combine(root, "match-0", "journal.json");
                var path2 = Path.Combine(root, "match-1", "journal.json");
                IdentityFiles.Write(path1, first); IdentityFiles.Write(path2, second);
                Assert(IdentityRecoveryEngine.Attempt(ref first, new FakeChannel(), x => { IdentityFiles.Write(path1, x); return true; }), "first not restored");
                Assert(IdentityFiles.Read<IdentityJournal>(path2) == second, "other journal changed");
            }
            finally { Directory.Delete(root, recursive: true); }
        });
        IdentitySessionTests.Run(Test);
        IdentityHandoffTests.Run(Test);
        IdentitySupervisorTests.Run(Test);
        IdentityPreparationTests.Run(Test);
        Console.WriteLine($"{passed} offline recovery/lifecycle tests passed; no Steam calls.");
        return 0;
    }

    private sealed class FakeChannel : IIdentityRecoveryChannel
    {
        public bool AccountMatches { get; set; } = true;
        public bool BlockSettled { get; set; } = true;
        public int Relationship { get; set; } = 3;
        internal bool RestoreFailure, RestoreSettled = true;
        internal int Restores, Inspections;
        internal readonly Queue<IdentityPage> Pages = new();
        public IdentityPage Inspect(int timeoutMs = 12000) { Inspections++; return Pages.Count > 0 ? Pages.Dequeue() : Clear; }
        public bool Restore() { Restores++; if (RestoreFailure) throw new IOException("offline"); return RestoreSettled; }
        public void Wait(int milliseconds) { }
    }
}
