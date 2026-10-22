using System.Diagnostics;
using NightreignP2PHelper;

internal static class IdentityHandoffTests
{
    private static void Assert(bool value, string message)
    { if (!value) throw new Exception(message); }

    private static void InTemporaryDirectory(Action<string> work)
    {
        var root = Path.Combine(Path.GetTempPath(), "nr-handoff-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try { work(root); }
        finally { Directory.Delete(root, recursive: true); }
    }

    internal static void Run(Action<string, Action> test)
    {
        test("client heartbeat pauses below thirty seconds retain hold but app death expires", () => {
            var now = DateTimeOffset.UtcNow;
            Assert(IdentityRecoveryHandoff.FreshClient(now.AddSeconds(-6), now), "old five-second cutoff retained");
            Assert(IdentityRecoveryHandoff.FreshClient(now.AddMilliseconds(-29_999), now), "brief pause expired lease");
            Assert(!IdentityRecoveryHandoff.FreshClient(now.AddSeconds(-30), now), "dead app lease held indefinitely");
            Assert(IdentityRecoveryHandoff.BrowserWatchdogMs > IdentityRecoveryHandoff.ClientLeaseMs,
                "browser watchdog can preempt the application lease");
        });
        test("recovery cooldown is durable before launch and shared by a fresh worker", () => InTemporaryDirectory(root => {
            var now = DateTimeOffset.UtcNow; var launches = 0;
            IdentityRecoveryHandoff.Schedule(root, now, () => {
                launches++;
                Assert(IdentityRecoveryHandoff.RemainingDelay(root, now) == 15_000, "launch preceded cooldown commit");
            });
            Assert(launches == 1 && IdentityRecoveryHandoff.RemainingDelay(root, now.AddSeconds(5)) == 10_000,
                "new process can bypass retry deadline");
            Assert(IdentityRecoveryHandoff.RemainingDelay(root, now.AddSeconds(15)) == 0,
                "cooldown failed to expire");
        }));
        test("launch failure leaves the recovery journal and cooldown owned", () => InTemporaryDirectory(root => {
            var now = DateTimeOffset.UtcNow;
            var path = Path.Combine(root, "journal.json");
            var journal = new IdentityJournal("76561198049468922", "76561198049468923",
                Guid.NewGuid().ToString("N"), 0, true, true, true, now);
            IdentityFiles.Write(path, journal);
            try
            {
                IdentityRecoveryHandoff.Schedule(root, now, () => throw new IOException());
                throw new Exception("expected launch failure");
            }
            catch (IOException) { }
            Assert(IdentityFiles.Read<IdentityJournal>(path) == journal
                && IdentityRecoveryHandoff.RemainingDelay(root, now) == 15_000,
                "failed transfer lost durable recovery ownership");
        }));
        test("cooldown write failure forbids launching a replacement", () => InTemporaryDirectory(root => {
            var blocked = Path.Combine(root, "not-a-directory"); File.WriteAllText(blocked, "occupied");
            var launched = false;
            try
            {
                IdentityRecoveryHandoff.Schedule(blocked, DateTimeOffset.UtcNow, () => launched = true);
                throw new Exception("expected disk failure");
            }
            catch (IOException) { }
            Assert(!launched, "replacement launched without durable backoff");
        }));
        test("future or expired retry timestamps cannot create unlimited waits", () => InTemporaryDirectory(root => {
            var now = DateTimeOffset.UtcNow;
            Assert(IdentityRecoveryHandoff.RemainingDelay(root, now) == 0, "fresh worker inherited phantom cooldown");
            IdentityFiles.Write(Path.Combine(root, "next-recovery.json"), new { not_before = now.AddDays(1) });
            Assert(IdentityRecoveryHandoff.RemainingDelay(root, now) == 15_000, "future clock jump stalled recovery");
            IdentityFiles.Write(Path.Combine(root, "next-recovery.json"), new { not_before = now.AddDays(-1) });
            Assert(IdentityRecoveryHandoff.RemainingDelay(root, now) == 0, "expired retry delayed recovery");
        }));
        test("finite task lock rejects duplicate owners and becomes available after exit", () => InTemporaryDirectory(root => {
            using var owner = IdentityRecoveryHandoff.TakeWorkerLock(root)
                ?? throw new Exception("initial owner failed");
            Assert(IdentityRecoveryHandoff.TakeWorkerLock(root) is null, "duplicate task acquired an occupied slot");
            owner.Dispose();
            using var next = IdentityRecoveryHandoff.TakeWorkerLock(root);
            Assert(next is not null, "next task could not take released lock");
        }));
    }
}
