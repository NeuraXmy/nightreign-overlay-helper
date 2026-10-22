using NightreignP2PHelper;

internal static class IdentitySessionTests
{
    private static readonly DateTimeOffset Now = DateTimeOffset.UtcNow;
    private static IdentityRequest Request() => new(Guid.NewGuid().ToString("N"), "76561198049468923",
        Guid.NewGuid().ToString("N"), Now, "76561198049468922");
    private static IdentityRequestEnvironment Ready => new(Now, true, false, true);
    private static void Assert(bool value, string message)
    { if (!value) throw new Exception(message); }

    internal static void Run(Action<string, Action> test)
    {
        test("idle IPC never connects or inspects game/client state", () => {
            var calls = new List<string>();
            for (int i = 0; i < 100; i++)
                Assert(IdentitySessionCoordinator.Run(null, false, _ => throw new Exception("idle inspected"),
                    () => { calls.Add("connect"); return true; }, () => calls.Add("work"), () => calls.Add("disconnect"))
                    == IdentitySessionResult.Idle, "idle not recognized");
            Assert(calls.Count == 0, "idle created a Steam session");
        });
        test("valid request connects only within task and releases before returning", () => {
            var calls = new List<string>();
            var result = IdentitySessionCoordinator.Run(Request(), false,
                _ => { calls.Add("inspect"); return Ready; },
                () => { calls.Add("connect"); return true; }, () => calls.Add("work"), () => calls.Add("disconnect"));
            Assert(result == IdentitySessionResult.Completed, "valid request rejected");
            Assert(string.Join(",", calls) == "inspect,connect,inspect,work,disconnect", "incorrect session ordering");
        });
        test("stale future malformed and cancelled requests never connect", () => {
            var request = Request();
            var cases = new[] {
                (request with { CreatedAt = Now.AddSeconds(-16) }, Ready),
                (request with { CreatedAt = Now.AddSeconds(6) }, Ready),
                (request with { Transaction = "invalid" }, Ready),
                (request with { Client = "invalid" }, Ready),
                (request with { Target = "0" }, Ready),
                (request with { ExpectedAccount = "" }, Ready),
                (request with { ExpectedAccount = request.Target }, Ready),
                (request, Ready with { Cancelled = true }),
                (request, Ready with { ClientAlive = false }),
                (request, Ready with { GameRunning = false }),
            };
            foreach (var (candidate, context) in cases)
            {
                var connections = 0;
                var result = IdentitySessionCoordinator.Run(candidate, false, _ => context,
                    () => { connections++; return true; }, () => throw new Exception("rejected work ran"),
                    () => throw new Exception("rejected request opened session"));
                Assert(result == IdentitySessionResult.Rejected && connections == 0, "invalid request connected");
            }
        });
        test("game exit cancellation and expiry during connection prevent action and release", () => {
            foreach (var context in new[] { Ready with { GameRunning = false }, Ready with { Cancelled = true },
                Ready with { ClientAlive = false }, Ready with { Now = Now.AddSeconds(16) } })
            {
                var inspections = 0; var releases = 0;
                var result = IdentitySessionCoordinator.Run(Request(), false,
                    _ => ++inspections == 1 ? Ready : context, () => true,
                    () => throw new Exception("obsolete action ran"), () => releases++);
                Assert(result == IdentitySessionResult.Rejected && releases == 1, "post-connect rejection leaked session");
            }
        });
        test("failed connection releases any partial session and can retry", () => {
            var releases = 0; var work = 0;
            Assert(IdentitySessionCoordinator.Run(Request(), false, _ => Ready, () => false,
                () => work++, () => releases++) == IdentitySessionResult.Unavailable, "offline result wrong");
            Assert(releases == 1 && work == 0, "failed connection leaked or acted");
            Assert(IdentitySessionCoordinator.Run(Request(), false, _ => Ready, () => true,
                () => work++, () => releases++) == IdentitySessionResult.Completed, "retry failed");
            Assert(releases == 2 && work == 1, "retry session leaked");
        });
        test("failed SDK Init skips wrapper Shutdown then successful retry balances callbacks", () => {
            bool initialized = false; int dispatcherCount = 0, shutdowns = 0, work = 0;
            void Shutdown() { shutdowns++; dispatcherCount--; }
            void Disconnect() => IdentitySessionCoordinator.Release(ref initialized, Shutdown);
            var failed = IdentitySessionCoordinator.Run(Request(), false, _ => Ready,
                () => { initialized = false; return false; }, () => work++, Disconnect);
            Assert(failed == IdentitySessionResult.Unavailable && shutdowns == 0 && dispatcherCount == 0,
                "Shutdown after failed Init poisoned Steamworks.NET dispatcher");
            var success = IdentitySessionCoordinator.Run(Request(), false, _ => Ready,
                () => { initialized = true; dispatcherCount++; return true; },
                () => { Assert(initialized && dispatcherCount == 1, "callbacks not initialized"); work++; }, Disconnect);
            Assert(success == IdentitySessionResult.Completed && shutdowns == 1 && dispatcherCount == 0
                && work == 1 && !initialized, "successful session was not balanced");
            Disconnect();
            Assert(shutdowns == 1 && dispatcherCount == 0, "duplicate Shutdown decremented dispatcher");
        });
        test("successful SDK Init without Steam login still shuts down", () => {
            bool initialized = false; int shutdowns = 0;
            var result = IdentitySessionCoordinator.Run(Request(), false, _ => Ready,
                () => { initialized = true; return false; }, () => throw new Exception("offline action ran"),
                () => IdentitySessionCoordinator.Release(ref initialized, () => shutdowns++));
            Assert(result == IdentitySessionResult.Unavailable && shutdowns == 1 && !initialized,
                "successful initialization with failed login retained session");
        });
        test("connection and task exceptions both release session", () => {
            foreach (var stage in new[] { "connect", "work", "recheck" })
            {
                var releases = 0; var inspections = 0;
                try
                {
                    IdentitySessionCoordinator.Run(Request(), false,
                        _ => { if (++inspections == 2 && stage == "recheck") throw new IOException(); return Ready; },
                        () => stage == "connect" ? throw new IOException() : true,
                        () => throw new IOException(), () => releases++);
                    throw new Exception("expected exception missing");
                }
                catch (IOException) { }
                Assert(releases == 1, stage + " exception leaked session");
            }
        });
        test("pending recovery connects without game or UI and keeps journal on failed login", () => {
            var journal = new IdentityJournal("76561198049468922", "76561198049468923",
                Guid.NewGuid().ToString("N"), 3, true, true, true, Now);
            var connections = 0; var releases = 0;
            var result = IdentitySessionCoordinator.Run(null, true, _ => throw new Exception("recovery depends on game/UI"),
                () => { connections++; return false; }, () => throw new Exception("offline recovery ran"), () => releases++);
            Assert(result == IdentitySessionResult.Unavailable && connections == 1 && releases == 1
                && journal.RecoveryNeeded, "offline recovery lost ownership");
            var channel = new RecoveryChannel();
            result = IdentitySessionCoordinator.Run(null, true, _ => throw new Exception("recovery depends on game/UI"),
                () => { connections++; return true; },
                () => Assert(IdentityRecoveryEngine.Attempt(ref journal, channel, _ => true), "recovery failed"),
                () => releases++);
            Assert(result == IdentitySessionResult.Completed && !journal.RecoveryNeeded && releases == 2, "recovery retry not released");
        });
        test("finite recovery keeps observations together then releases before a new attempt", () => {
            var journal = new IdentityJournal("76561198049468922", "76561198049468923",
                Guid.NewGuid().ToString("N"), 3, true, true, true, Now);
            var releases = 0; var connections = 0; var htmlReleased = false;
            var first = IdentitySessionCoordinator.RunRecoveryAttempt(
                () => { connections++; return true; }, () => {
                    try
                    {
                        Assert(releases == 0, "shutdown interrupted observations");
                        return IdentityRecoveryEngine.Attempt(ref journal,
                            new RecoveryChannel { RestoreSettled = false }, _ => true);
                    }
                    finally { htmlReleased = true; }
                }, () => { Assert(htmlReleased, "SDK released before HTML"); releases++; });
            Assert(first == IdentitySessionResult.RecoveryPending && releases == 1 && journal.RecoveryNeeded,
                "failed attempt leaked registration or discarded journal");
            var second = IdentitySessionCoordinator.RunRecoveryAttempt(
                () => { connections++; return true; },
                () => IdentityRecoveryEngine.Attempt(ref journal, new RecoveryChannel(), _ => true), () => releases++);
            Assert(second == IdentitySessionResult.Completed && connections == 2 && releases == 2
                && !journal.RecoveryNeeded, "fresh retry did not recover and release");
        });
        test("failed recovery login and exceptions release the finite session", () => {
            var releases = 0;
            Assert(IdentitySessionCoordinator.RunRecoveryAttempt(() => false,
                () => throw new Exception("offline mutation"), () => releases++) == IdentitySessionResult.Unavailable,
                "failed recovery login accepted");
            foreach (var connectionThrows in new[] { true, false })
            {
                try
                {
                    IdentitySessionCoordinator.RunRecoveryAttempt(
                        () => connectionThrows ? throw new IOException() : true,
                        () => throw new IOException(), () => releases++);
                    throw new Exception("expected failure");
                }
                catch (IOException) { }
            }
            Assert(releases == 3, "exception or login failure retained SDK");
        });
        test("HTML cleanup failures still release every browser callback and surface", () => {
            var order = new List<string>();
            try
            {
                IdentitySessionCoordinator.ReleaseResources(new Action[] {
                    () => { order.Add("browser1"); throw new IOException(); },
                    () => order.Add("browser2"),
                    () => { order.Add("callback"); throw new InvalidOperationException(); },
                    () => order.Add("HTML.Shutdown") });
                throw new Exception("cleanup failure lost");
            }
            catch (IOException) { }
            Assert(string.Join(",", order) == "browser1,browser2,callback,HTML.Shutdown", "cleanup stopped early");
        });
    }

    private sealed class RecoveryChannel : IIdentityRecoveryChannel
    {
        public bool AccountMatches => true;
        public bool BlockSettled { get; set; } = true;
        public int Relationship => 3;
        internal bool RestoreSettled = true;
        public IdentityPage Inspect(int timeoutMs = 12000) => new(true, true, false, true);
        public bool Restore() => RestoreSettled;
        public void Wait(int milliseconds) { }
    }
}
