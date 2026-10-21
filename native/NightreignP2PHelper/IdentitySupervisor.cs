using System.Diagnostics;

namespace NightreignP2PHelper;

// This process never initializes Steam, sets an AppID or loads steam_api64.dll.
// Registered task children never spawn successors. Their exit clears Steam's
// running-app process entry while this independent owner retains recovery IPC.
internal static class IdentitySupervisor
{
    internal static int Run(int? slot = null, string? testRoot = null, Func<Process>? taskFactory = null,
        Func<DateTimeOffset>? utcNow = null, Action<int>? pause = null, Func<bool>? stop = null)
    {
        if (slot is not null && slot is not (0 or 1)) return 2;
        var root = testRoot ?? (slot is null ? IdentityFiles.Root : Path.Combine(IdentityFiles.Root, "match-" + slot));
        Directory.CreateDirectory(root);
        Directory.CreateDirectory(Path.Combine(root, "requests"));
        Directory.CreateDirectory(Path.Combine(root, "clients"));
        Directory.CreateDirectory(Path.Combine(root, "results"));
        FileStream singleton;
        try { singleton = new FileStream(Path.Combine(root, "supervisor.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
        catch (IOException) { return 0; }
        utcNow ??= () => DateTimeOffset.UtcNow;
        pause ??= Thread.Sleep;
        taskFactory ??= () => StartTask(slot);
        using (singleton)
        {
            var lastClient = utcNow();
            // A legacy worker owns only worker.lock and writes its old capability.
            // Do not advertise v5 or refresh that file while it is still alive:
            // a new client lease could otherwise keep the old owner alive forever.
            while (true)
            {
                using var priorOwner = IdentityRecoveryHandoff.TakeWorkerLock(root);
                if (priorOwner is not null) break;
                if (stop?.Invoke() == true) return 0;
                pause(150);
            }
            lastClient = utcNow();
            var nextIdleHeartbeat = DateTimeOffset.MinValue;
            try
            {
                while (stop?.Invoke() != true)
                {
                    try
                    {
                        var pending = HasPending(root, out var unreadable);
                        if (unreadable)
                        {
                            Status(root, slot, "recovery_pending", "恢复记录损坏，停止自动操作；请在 Steam 核对屏蔽列表", false);
                            pause(1000); continue;
                        }
                        if (Directory.EnumerateFiles(Path.Combine(root, "clients"), "*.json")
                            .Any(path => IdentityRecoveryHandoff.FreshClient(File.GetLastWriteTimeUtc(path), utcNow())))
                            lastClient = utcNow();
                        var work = pending || File.Exists(Path.Combine(root, "active-request.json"))
                            || Directory.EnumerateFiles(Path.Combine(root, "requests"), "*.json").Any();
                        if (work)
                        {
                            var delay = IdentityRecoveryHandoff.RemainingDelay(root, utcNow());
                            for (int elapsed = 0; elapsed < delay; elapsed += 100)
                            {
                                if (elapsed % 1000 == 0)
                                    Status(root, slot, "recovery_pending", "等待恢复重试；监督组件未连接 Steam", false);
                                pause(Math.Min(100, delay - elapsed));
                            }
                            Process task;
                            while (true)
                            {
                                using var dispatch = IdentityRecoveryHandoff.TakeWorkerLock(root);
                                if (dispatch is not null) { task = taskFactory(); break; }
                                if (stop?.Invoke() == true) return 0;
                                pause(150);
                            }
                            using var activeTask = task;
                            var taskClock = Stopwatch.StartNew();
                            long lastHeartbeat = 0;
                            DateTimeOffset lastReported = DateTimeOffset.MinValue;
                            // Do not refresh task telemetry here: a stuck task
                            // must remain stale so the client's lease can expire.
                            while (!task.WaitForExit(100))
                            {
                                try
                                {
                                    var heartbeat = IdentityFiles.Read<TaskHeartbeat>(Path.Combine(root, "status.json"));
                                    if (heartbeat?.TaskPid == task.Id && heartbeat.UpdatedAt > lastReported)
                                    {
                                        lastReported = heartbeat.UpdatedAt;
                                        lastHeartbeat = taskClock.ElapsedMilliseconds;
                                    }
                                }
                                catch { }
                                if (TaskExpired(taskClock.ElapsedMilliseconds, lastHeartbeat))
                                {
                                    // Kill only this owned child. Its durable journal is
                                    // compensated by the next finite task, never replayed.
                                    task.Kill();
                                    task.WaitForExit(5000);
                                    break;
                                }
                            }
                            // Completion is durable in results/journals. Keep the
                            // task's terminal status for one UI poll before idle.
                            pause(1500);
                            if (HasPending(root, out _))
                            {
                                try { IdentityRecoveryHandoff.Schedule(root, utcNow(), () => { }); }
                                catch { }
                            }
                            continue;
                        }
                        if (utcNow() >= nextIdleHeartbeat)
                        {
                            Status(root, slot, "idle", "队友通信组件已就绪（监督组件未连接 Steam）", true);
                            nextIdleHeartbeat = utcNow().AddMilliseconds(750);
                        }
                        if (utcNow() - lastClient > TimeSpan.FromSeconds(60)) return 0;
                        pause(150);
                    }
                    catch
                    {
                        Status(root, slot, "recovery_pending", "监督组件重试启动；通信恢复记录已保留", false);
                        pause(IdentityRecoveryHandoff.RetryMs);
                    }
                }
                return 0;
            }
            finally { Status(root, slot, "idle", "通信监督组件已退出", false, exiting: true); }
        }
    }

    private sealed record TaskHeartbeat(int? TaskPid, DateTimeOffset UpdatedAt);
    internal static bool TaskExpired(long elapsed, long lastHeartbeat)
        => elapsed - lastHeartbeat >= 120_000 || elapsed >= (4 * 60 + 10) * 60_000;

    internal static bool HasPending(string root, out bool unreadable)
    {
        unreadable = false; var pending = false;
        foreach (var path in Directory.EnumerateFiles(root, "journal-*.json"))
        {
            try
            {
                var journal = IdentityFiles.Read<IdentityJournal>(path);
                if (journal is null || !IdentityRules.ValidSteamId(journal.Account) || !IdentityRules.ValidSteamId(journal.Target)
                    || journal.Account == journal.Target || !Guid.TryParseExact(journal.Transaction, "N", out _)
                    || journal.OriginalRelationship is not (0 or 3)
                    || Path.GetFileName(path) != "journal-" + journal.Account + ".json") throw new InvalidDataException();
                pending |= journal.RecoveryNeeded;
            }
            catch { unreadable = true; }
        }
        return pending;
    }

    [System.Diagnostics.CodeAnalysis.UnconditionalSuppressMessage("SingleFile", "IL3000",
        Justification = "Assembly.Location is used only when launched by the dotnet host; single-file executables start Environment.ProcessPath directly.")]
    private static Process StartTask(int? slot)
    {
        var path = Environment.ProcessPath ?? throw new IOException("通信组件路径不可用");
        var start = new ProcessStartInfo(path) { UseShellExecute = false, CreateNoWindow = true,
            WorkingDirectory = AppContext.BaseDirectory };
        if (Path.GetFileNameWithoutExtension(path).Equals("dotnet", StringComparison.OrdinalIgnoreCase))
            start.ArgumentList.Add(typeof(Program).Assembly.Location);
        start.ArgumentList.Add(slot is null ? "--identity-task" : "--match-task");
        if (slot is not null) start.ArgumentList.Add(slot.Value.ToString());
        start.ArgumentList.Add(Environment.ProcessId.ToString());
        // Never pass an inherited game registration to a future task.
        start.Environment.Remove("SteamAppId"); start.Environment.Remove("SteamGameId");
        return Process.Start(start) ?? throw new IOException("无法启动通信任务组件");
    }

    private static void Status(string root, int? slot, string state, string message, bool ready, bool exiting = false)
    {
        try
        {
            // Hold the same lock through the capability write, not just a probe.
            // An old helper started after supervisor setup must not be kept alive
            // by new-version leases while it owns this slot.
            using var gate = IdentityRecoveryHandoff.TakeWorkerLock(root);
            if (gate is null) return;
            IdentityFiles.Write(Path.Combine(root, "status.json"), new {
                state, message, target = "", transaction = "", account = "", accepts_begin = ready,
                updated_at = DateTimeOffset.UtcNow, worker_pid = Environment.ProcessId,
                task_pid = (int?)null, task_exiting = false, steam_connected = false,
                worker_exiting = exiting, hold_end_reason = "", diagnostic_code = "",
                steam_lifecycle = slot is null ? "recovery_only_v3" : "match_hold_v5" });
        }
        catch { }
    }
}
