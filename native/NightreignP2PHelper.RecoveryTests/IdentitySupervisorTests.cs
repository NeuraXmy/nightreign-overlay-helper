using System.Diagnostics;
using System.Text.Json;
using NightreignP2PHelper;

internal static class IdentitySupervisorTests
{
    private sealed record Attempts(int Count);
    private static void Assert(bool value, string message)
    { if (!value) throw new Exception(message); }

    private static void InTemporaryDirectory(Action<string> work)
    {
        var root = Path.Combine(Path.GetTempPath(), "nr-supervisor-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try { work(root); }
        finally { Directory.Delete(root, recursive: true); }
    }

    internal static int TaskChild(string root, int supervisorPid)
    {
        using var taskLock = IdentityRecoveryHandoff.TakeWorkerLock(root);
        if (taskLock is null) return 3;
        var path = Path.Combine(root, "journal-76561198049468922.json");
        var journal = IdentityFiles.Read<IdentityJournal>(path)!;
        var previous = IdentityFiles.Read<Attempts>(Path.Combine(root, "attempts.json"));
        var attempt = (previous?.Count ?? 0) + 1;
        IdentityFiles.Write(Path.Combine(root, "attempts.json"), new Attempts(attempt));
        IdentityFiles.Write(Path.Combine(root, "status.json"), new {
            state = "fake_task_owns_heartbeat", task_pid = Environment.ProcessId,
            worker_pid = supervisorPid, updated_at = DateTimeOffset.UtcNow });
        Thread.Sleep(350);
        using var telemetry = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "status.json")));
        if (telemetry.RootElement.GetProperty("task_pid").GetInt32() != Environment.ProcessId
            || telemetry.RootElement.GetProperty("state").GetString() != "fake_task_owns_heartbeat") return 4;
        if (attempt == 1)
            IdentityRecoveryHandoff.Schedule(root, DateTimeOffset.UtcNow, () => { });
        else IdentityFiles.Write(path, journal with { RecoveryNeeded = false });
        return 0;
    }

    internal static void Run(Action<string, Action> test)
    {
        test("unregistered supervisor retries exited task without UI and preserves child heartbeat", () => InTemporaryDirectory(root => {
            var now = DateTimeOffset.UtcNow; var journal = new IdentityJournal("76561198049468922", "76561198049468923",
                Guid.NewGuid().ToString("N"), 0, true, true, true, now);
            IdentityFiles.Write(Path.Combine(root, "journal-76561198049468922.json"), journal);
            var starts = 0; var failedStart = false; var children = new List<int>();
            IdentitySupervisor.Run(testRoot: root, utcNow: () => now,
                pause: ms => now = now.AddMilliseconds(ms),
                stop: () => starts == 2 && !IdentitySupervisor.HasPending(root, out _),
                taskFactory: () => {
                    if (!failedStart) { failedStart = true; throw new IOException("simulated start failure"); }
                    starts++;
                    Assert(IdentitySupervisor.Run(testRoot: root, stop: () => true) == 0,
                        "duplicate supervisor entered occupied root");
                    var start = new ProcessStartInfo("dotnet") { UseShellExecute = false, CreateNoWindow = true };
                    start.ArgumentList.Add(typeof(IdentitySupervisorTests).Assembly.Location);
                    start.ArgumentList.Add("--supervisor-test-task"); start.ArgumentList.Add(root);
                    start.ArgumentList.Add(Environment.ProcessId.ToString());
                    var child = Process.Start(start) ?? throw new Exception("child did not start");
                    children.Add(child.Id); return child;
                });
            Assert(failedStart && starts == 2 && children.Distinct().Count() == 2,
                "task did not exit and get replaced by supervisor");
            Assert(!IdentityFiles.Read<IdentityJournal>(Path.Combine(root, "journal-76561198049468922.json"))!.RecoveryNeeded,
                "independent retry failed to commit completion");
            Assert(now - journal.CreatedAt >= TimeSpan.FromSeconds(30), "start failure/recovery bypassed local backoff");
        }));
        test("supervisor preserves corrupt journal and never launches an action", () => InTemporaryDirectory(root => {
            var path = Path.Combine(root, "journal-broken.json"); File.WriteAllText(path, "malformed original bytes");
            var ticks = 0;
            IdentitySupervisor.Run(testRoot: root, taskFactory: () => throw new Exception("corrupt journal started task"),
                stop: () => ticks > 1, pause: _ => ticks++);
            Assert(File.ReadAllText(path) == "malformed original bytes", "corrupt recovery evidence overwritten");
        }));
        test("idle supervisor exits after client grace without starting any Steam task", () => InTemporaryDirectory(root => {
            var now = DateTimeOffset.UtcNow; var start = now; var starts = 0;
            Assert(IdentitySupervisor.Run(testRoot: root, utcNow: () => now,
                taskFactory: () => { starts++; throw new Exception("idle launched task"); },
                pause: ms => now = now.AddMilliseconds(ms)) == 0, "idle supervisor did not finish");
            Assert(starts == 0 && now - start > TimeSpan.FromSeconds(60), "idle path skipped client grace");
            using var status = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "status.json")));
            Assert(!status.RootElement.GetProperty("steam_connected").GetBoolean()
                && status.RootElement.GetProperty("worker_exiting").GetBoolean(), "idle retained Steam registration");
        }));
        test("supervisor cannot advertise new capability while legacy worker owns the task lock", () => InTemporaryDirectory(root => {
            var status = Path.Combine(root, "status.json"); File.WriteAllText(status, "legacy status must remain");
            using var legacy = IdentityRecoveryHandoff.TakeWorkerLock(root) ?? throw new Exception("legacy lock failed");
            var waits = 0;
            IdentitySupervisor.Run(testRoot: root, stop: () => waits >= 3,
                taskFactory: () => throw new Exception("new task overlapped legacy"), pause: _ => {
                    Assert(File.ReadAllText(status) == "legacy status must remain", "legacy status was replaced by v4");
                    waits++;
                });
            Assert(waits == 3 && File.ReadAllText(status) == "legacy status must remain", "startup renewed old worker state");
        }));
        test("late legacy owner prevents idle heartbeat capability replacement", () => InTemporaryDirectory(root => {
            var status = Path.Combine(root, "status.json"); var now = DateTimeOffset.UtcNow;
            FileStream? legacy = null; var waits = 0;
            try
            {
                IdentitySupervisor.Run(testRoot: root, utcNow: () => now, stop: () => waits >= 10,
                    taskFactory: () => throw new Exception("idle launched task"), pause: ms => {
                        now = now.AddMilliseconds(ms); waits++;
                        if (legacy is null)
                        {
                            legacy = IdentityRecoveryHandoff.TakeWorkerLock(root) ?? throw new Exception("late lock failed");
                            File.WriteAllText(status, "late legacy owns status");
                        }
                        else Assert(File.ReadAllText(status) == "late legacy owns status", "v4 renewed late legacy owner");
                    });
                Assert(File.ReadAllText(status) == "late legacy owns status", "supervisor exit replaced old capability");
            }
            finally { legacy?.Dispose(); }
        }));
    }
}
