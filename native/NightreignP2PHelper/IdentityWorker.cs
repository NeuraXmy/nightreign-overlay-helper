using System.Diagnostics;
using System.Runtime.InteropServices;
using Steamworks;

namespace NightreignP2PHelper;

internal static class IdentityWorker
{
    private static string Root = IdentityFiles.Root;
    private static bool matchMode;
    private static bool steamReady;
    private static nint library;
    private static bool resolverInstalled;
    private static long lastHeartbeat;
    private static readonly Stopwatch Clock = Stopwatch.StartNew();
    private static string state = "preparing", message = "正在检查通信恢复记录", account = "", target = "", transaction = "";
    private static bool workerExiting;
    private static bool workerStarted;
    private static int supervisorPid;
    private static string holdEndReason = "";
    private static string diagnosticCode = "";

    internal static int Run(int? matchSlot = null, int? supervisorPid = null)
    {
        workerStarted = true;
        IdentityWorker.supervisorPid = supervisorPid ?? Environment.ProcessId;
        if (matchSlot is not null)
        {
            if (matchSlot is not (0 or 1)) return 2;
            matchMode = true;
            Root = Path.Combine(IdentityFiles.Root, "match-" + matchSlot);
        }
        Directory.CreateDirectory(Root);
        Directory.CreateDirectory(Path.Combine(Root, "requests"));
        Directory.CreateDirectory(Path.Combine(Root, "clients"));
        Directory.CreateDirectory(Path.Combine(Root, "results"));
        var singleton = IdentityRecoveryHandoff.TakeWorkerLock(Root, waitMs: supervisorPid is null ? 0 : 10_000);
        if (singleton is null) return 0;
        using (singleton)
        {
            // Deliberately no parent process, console-input or game-exit cancellation.
            // Pending journals are retained and retried even after the overlay exits.
            try
            {
                while (true)
                {
                  try
                  {
                    Tick();
                    var journals = ReadPending(out bool unreadable);
                    if (unreadable)
                    {
                        Set("recovery_pending", "恢复记录损坏，已停止自动操作；请在 Steam 核对屏蔽列表");
                        return FinishWorker();
                    }
                    RecoverAbandonedClaim(journals);
                    if (journals.Count > 0)
                    {
                        target = journals[0].Target; transaction = journals[0].Transaction;
                        var result = IdentitySessionCoordinator.RunRecoveryAttempt(Connect, () =>
                        {
                            account = SteamUser.GetSteamID().ToString();
                            var pending = journals.FirstOrDefault(x => x.Account == account);
                            if (pending is null)
                            {
                                Set("recovery_pending", "请登录原 Steam 账号以恢复上次暂时屏蔽的队友");
                                return false;
                            }
                            using var accountLock = LockAccount(account);
                            using var targetLock = LockTarget(account, pending.Target);
                            return Recover(pending, null);
                        }, Disconnect);
                        if (result == IdentitySessionResult.Unavailable)
                            Set("recovery_pending", "通信恢复等待 Steam 登录和联网；请勿删除恢复记录");
                        if (NoPendingRecovery()) return FinishWorker();
                        return FinishForRetry();
                    }
                    // File IPC and request validation do not require a Steam
                    // session. Idle workers must never register the game as running.
                    var request = NextRequest();
                    if (request is not null)
                    {
                        target = request.Target; transaction = request.Transaction;
                        Set("preparing", "正在检查识别请求");
                        var result = IdentitySessionCoordinator.Run(request, false, InspectRequest, Connect, () =>
                        {
                            account = SteamUser.GetSteamID().ToString();
                            using var accountLock = LockAccount(account);
                            Begin(request);
                        }, Disconnect);
                        if (result is IdentitySessionResult.Rejected or IdentitySessionResult.Unavailable)
                        {
                            Set("error", result == IdentitySessionResult.Rejected
                                ? "识别请求已取消或过期，或游戏尚未运行；未修改通信状态"
                                : "无法连接 Steam，请登录后重试；未修改通信状态", true,
                                result == IdentitySessionResult.Unavailable ? "steam_connect" : "prepare_cancelled");
                            Result(transaction, target, state, message, diagnosticCode);
                            ClearClaim();
                        }
                        if (NoPendingRecovery()) return FinishWorker();
                        return FinishForRetry();
                    }
                    if (state != "restored")
                    { target = ""; transaction = ""; Set("idle", "队友身份识别已就绪（按需连接 Steam）", true); }
                    return FinishWorker();
                  }
                  catch
                  {
                      // A transient filesystem/Steam error must not kill the detached
                      // recovery owner. The last durable journal remains authoritative.
                      Set("recovery_pending", "识别组件正在重连；通信恢复记录已保留");
                      return FinishForRetry();
                  }
                }
            }
            finally
            {
                Disconnect();
                if (library != 0) NativeLibrary.Free(library);
            }
        }
    }

    private static bool NoPendingRecovery()
        => ReadPending(out var unreadable).Count == 0 && !unreadable;

    private static int FinishWorker()
    {
        // Some Steam clients retain the AppID process registration after SDK
        // Shutdown. A Steam task's owner therefore exits instead of idling.
        workerExiting = true; Tick(true);
        return 0;
    }

    private static int FinishForRetry()
    {
        try
        {
            IdentityRecoveryHandoff.Schedule(Root, DateTimeOffset.UtcNow, () => { });
        }
        catch
        {
            Set("recovery_pending", "无法写入重试时间；独立监督组件仍会重试，恢复记录已保留");
        }
        return FinishWorker();
    }

    private static FileStream LockAccount(string id) => new(Path.Combine(Root, "account-" + id + ".lock"),
        FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
    private static FileStream LockTarget(string owner, string peer) => new(
        Path.Combine(IdentityFiles.Root, "target-" + owner + "-" + peer + ".lock"),
        FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
    private static string JournalPath(string id) => Path.Combine(Root, "journal-" + id + ".json");
    private static void Save(IdentityJournal journal) => IdentityFiles.Write(JournalPath(journal.Account), journal);
    private static bool TrySave(IdentityJournal journal)
    {
        try { Save(journal); return true; }
        catch { return false; } // Never interrupt compensation after a block was sent.
    }
    private static List<IdentityJournal> ReadPending(out bool unreadable)
    {
        unreadable = false; var pending = new List<IdentityJournal>();
        foreach (var path in Directory.EnumerateFiles(Root, "journal-*.json"))
        {
            try
            {
                var item = IdentityFiles.Read<IdentityJournal>(path);
                if (item is null || !IdentityRules.ValidSteamId(item.Account) || !IdentityRules.ValidSteamId(item.Target)
                    || item.Account == item.Target || !Guid.TryParseExact(item.Transaction, "N", out _)
                    || item.OriginalRelationship is not (0 or 3)
                    || Path.GetFileName(path) != "journal-" + item.Account + ".json") throw new InvalidDataException();
                if (item.RecoveryNeeded) pending.Add(item);
            }
            catch { unreadable = true; }
        }
        return pending;
    }
    private static IdentityRequest? NextRequest()
    {
        foreach (var path in Directory.EnumerateFiles(Path.Combine(Root, "requests"), "*.json").Order())
        {
            IdentityRequest? request = null;
            try { request = IdentityFiles.Read<IdentityRequest>(path); }
            catch { }
            if (request is null || !Guid.TryParseExact(request.Transaction, "N", out _)
                || !Guid.TryParseExact(request.Client, "N", out _) || !IdentityRules.ValidSteamId(request.Target)
                || !matchMode || !IdentityRules.ValidSteamId(request.ExpectedAccount)
                || request.Target == request.ExpectedAccount)
            { File.Delete(path); continue; }
            if (DateTimeOffset.UtcNow - request.CreatedAt > TimeSpan.FromSeconds(15)
                || request.CreatedAt > DateTimeOffset.UtcNow.AddSeconds(5) || !ClientAlive(request.Client))
            { Result(request.Transaction, request.Target, "error", "识别请求已过期，请在游戏中重试"); File.Delete(path); continue; }
            IdentityFiles.Write(Path.Combine(Root, "active-request.json"), request);
            File.Delete(path);
            return request;
        }
        return null;
    }
    private static bool ClientAlive(string id)
    {
        var path = Path.Combine(Root, "clients", id + ".json");
        return File.Exists(path) && IdentityRecoveryHandoff.FreshClient(File.GetLastWriteTimeUtc(path), DateTimeOffset.UtcNow);
    }
    private static IdentityRequestEnvironment InspectRequest(IdentityRequest request)
        => new(DateTimeOffset.UtcNow, ClientAlive(request.Client), RequestedRestore(request.Transaction), GameRunning());

    private static bool HoldAuthorized(IdentityRequest request)
    {
        if (!ClientAlive(request.Client)) return false;
        try
        {
            var lease = IdentityFiles.Read<MatchLease>(Path.Combine(Root, "clients", request.Client + ".json"));
            return lease?.HoldTarget == request.Target && lease.ExpectedAccount == request.ExpectedAccount;
        }
        catch { return false; }
    }
    private sealed record MatchLease(string HoldTarget, string ExpectedAccount);

    private static bool GameRunning()
    {
        Process[] games = Array.Empty<Process>();
        try
        {
            games = Process.GetProcessesByName("nightreign");
            return games.Any(game => !game.HasExited);
        }
        catch { return false; }
        finally { foreach (var game in games) game.Dispose(); }
    }
    private static bool RequestedRestore(string id) => File.Exists(Path.Combine(Root, "restore-" + id + ".json"));
    private static void RecoverAbandonedClaim(List<IdentityJournal> pending)
    {
        var path = Path.Combine(Root, "active-request.json");
        if (!File.Exists(path)) return;
        var claim = IdentityFiles.Read<IdentityRequest>(path);
        if (claim is null || !Guid.TryParseExact(claim.Transaction, "N", out _)) throw new InvalidDataException();
        if (pending.Any(x => x.Transaction == claim.Transaction)) return;
        // The previous worker ended between claiming the command and committing a
        // block journal. Never replay that command after a process restart.
        Result(claim.Transaction, claim.Target, "error", "上次识别已中断且没有待恢复的屏蔽，请重试");
        var queued = Path.Combine(Root, "requests", claim.Transaction + ".json");
        if (File.Exists(queued)) File.Delete(queued);
        File.Delete(path);
    }
    private static void ClearClaim()
    {
        try { File.Delete(Path.Combine(Root, "active-request.json")); }
        catch { }
    }

    private static void Begin(IdentityRequest request)
    {
        using var targetLock = LockTarget(account, request.Target);
        target = request.Target; transaction = request.Transaction;
        holdEndReason = "";
        Set("preparing", "正在确认队友和原始通信状态");
        IdentityJournal? journal = null;
        IdentityHtmlSession? html = null;
        string stage = "prepare_unknown";
        try
        {
            int original = 0;
            void Validate()
            {
                if (!ClientAlive(request.Client) || RequestedRestore(transaction)
                    || (matchMode && !HoldAuthorized(request)))
                    throw new IdentityPreparationException("prepare_cancelled", "请求已取消或助手续约失效，未修改通信状态");
                if (account != request.ExpectedAccount || !SteamUser.BLoggedOn()
                    || SteamUser.GetSteamID().ToString() != account)
                    throw new IdentityPreparationException("steam_account", "Steam 原账号已离线或切换，未修改通信状态");
                if (!GameRunning() || target == account || !ActivePeer(target))
                    throw new IdentityPreparationException("peer_departed", "游戏已退出或队友已离开，未修改通信状态");
                original = (int)SteamFriends.GetFriendRelationship(new CSteamID(ulong.Parse(target)));
                if (matchMode ? original != 0 : original is not (0 or 3))
                    throw new IdentityPreparationException("relationship_excluded", "好友或不符合条件的通信关系，未修改通信状态");
            }
            html = IdentityPreparation.Run(() =>
            {
                IdentityHtmlSession? candidate = null;
                try
                {
                    stage = "browser_start";
                    try { candidate = new IdentityHtmlSession(account, target, Tick); }
                    catch (Exception e) when (e is TimeoutException or InvalidOperationException)
                    { throw new IdentityPreparationException(stage, "Steam 网页组件启动失败或超时", true); }
                    stage = "page_timeout";
                    IdentityPage page;
                    try { page = candidate.Inspect(); }
                    catch (TimeoutException)
                    { throw new IdentityPreparationException(stage, "Steam 网页通信状态核验超时", true); }
                    IdentityPreparation.ValidatePage(page);
                    Validate();
                    return candidate;
                }
                catch { candidate?.Dispose(); throw; }
            }, Validate, Sleep, (attempt, failure) =>
                Set("preparing", $"{failure.Message}；正在重试准备（{attempt}/3）", code: failure.Code),
                matchMode ? 3 : 1);
            stage = "journal_write";
            var prepared = new IdentityJournal(account, target, transaction, original, false, false, true, DateTimeOffset.UtcNow);
            Save(prepared); // Failure here forbids sending block=1.
            journal = prepared; // Only now is there a transaction requiring compensation.
            var started = Clock.ElapsedMilliseconds;
            var outcome = IdentityRecoveryEngine.ConfirmBlock(ref journal, () => {
                html.StartBlock(matchMode ? IdentityRecoveryHandoff.BrowserWatchdogMs : 9000);
                return html.WaitBlock(2000)?.Tag != "precondition";
            }, () => html.Inspect(3500), () => html.BlockSettled, TrySave, matchMode);
            if (outcome == IdentityRecoveryEngine.BlockOutcome.Rejected)
            {
                // Explicit rejection proves no block was sent. Avoid compensating
                // an operation we never performed (or changing concurrent user intent).
                if (TrySave(journal with { RecoveryNeeded = false }))
                {
                    journal = null;
                    Set("error", "Steam 网页身份核对失败，未修改通信状态", true);
                    Result(transaction, target, state, message);
                    return;
                }
            }
            if (outcome == IdentityRecoveryEngine.BlockOutcome.Confirmed)
            {
                Set("blocked", matchMode ? "已暂时屏蔽非好友队友；离队或关闭开关后恢复" : "正在对应队友栏，随后自动恢复通信");
                if (matchMode)
                {
                    var end = IdentityRecoveryEngine.HoldMatch(started, () => Clock.ElapsedMilliseconds,
                        html.Wait, html.RenewHold, () => HoldAuthorized(request),
                        () => RequestedRestore(transaction), GameRunning,
                        () => SteamUser.BLoggedOn() && SteamUser.GetSteamID().ToString() == account);
                    holdEndReason = end switch {
                        IdentityRecoveryEngine.MatchHoldEnd.LeaseExpired => "client_lease_expired",
                        IdentityRecoveryEngine.MatchHoldEnd.RestoreRequested => "restore_requested",
                        IdentityRecoveryEngine.MatchHoldEnd.GameExited => "game_exited",
                        IdentityRecoveryEngine.MatchHoldEnd.AccountOffline => "account_offline",
                        _ => "four_hour_limit" };
                    Tick(true);
                }
                else
                    IdentityRecoveryEngine.Hold(started, () => Clock.ElapsedMilliseconds, html.Wait,
                        () => ClientAlive(request.Client), () => RequestedRestore(transaction), () => ActivePeer(target));
            }
        }
        catch (Exception failure)
        {
            if (journal is null)
            {
                var preparation = failure as IdentityPreparationException;
                Set("error", preparation is null
                    ? $"准备阶段失败（{stage}），未执行屏蔽"
                    : $"{preparation.Message}；本次准备已停止，未执行屏蔽", true,
                    preparation?.Code ?? stage);
                Result(transaction, target, state, message, diagnosticCode);
            }
        }
        finally
        {
            if (journal is not null)
            {
                // Even a failed/ambiguous block gets compensation; only our recorded
                // originally-unblocked target is eligible for restoration.
                if (html?.BlockSettled == true) { journal = journal with { BlockSettled = true }; TrySave(journal); }
                Recover(journal, html);
                html = null;
            }
            html?.Dispose();
            ClearClaim();
        }
    }

    private static bool Recover(IdentityJournal journal, IdentityHtmlSession? html)
    {
        account = journal.Account; target = journal.Target; transaction = journal.Transaction;
        try
        {
            try
            {
                if (!SteamUser.BLoggedOn() || SteamUser.GetSteamID().ToString() != account)
                {
                    Set("recovery_pending", "恢复等待原 Steam 账号在线；恢复记录会保留");
                    return false;
                }
                html ??= new IdentityHtmlSession(account, target, Tick);
                Set("restoring", "正在恢复队友通信");
                if (IdentityRecoveryEngine.Attempt(ref journal, new RecoveryChannel(html, account, target), TrySave))
                {
                    var code = IdentityRecoveryEngine.RestoredCode(journal);
                    Set("restored", code == "" ? "队友通信已恢复" : "屏蔽未确认成功；通信已恢复，等待重试", true, code);
                    Result(transaction, target, state, message, code);
                    ClearClaim();
                    var restore = Path.Combine(Root, "restore-" + transaction + ".json");
                    if (File.Exists(restore)) File.Delete(restore);
                    return true;
                }
                Set("recovery_pending", !journal.BlockSettled && !journal.BlockObserved
                    ? "原屏蔽请求结果未明；正在持续尝试恢复，请在 Steam 核对该队友"
                    : "通信恢复尚未确认；保持 Steam 在线后将继续重试");
            }
            catch
            {
                Set("recovery_pending", "暂时无法核对通信恢复；保持 Steam 在线，将自动重试");
            }
            // Unknown replies retain the journal. The finite attempt's process
            // can now exit; its successor resumes compensation after local delay.
            return false;
        }
        finally { html?.Dispose(); }
    }

    private sealed class RecoveryChannel(IdentityHtmlSession html, string owner, string peer) : IIdentityRecoveryChannel
    {
        public bool AccountMatches => SteamUser.BLoggedOn() && SteamUser.GetSteamID().ToString() == owner;
        public bool BlockSettled => html.BlockSettled;
        public int Relationship => (int)SteamFriends.GetFriendRelationship(new CSteamID(ulong.Parse(peer)));
        public IdentityPage Inspect(int timeoutMs = 12000) => html.Inspect(timeoutMs);
        public bool Restore() => html.Restore() is { Tag: "response", Ok: true };
        public void Wait(int milliseconds) => html.Wait(milliseconds);
    }

    private static bool ActivePeer(string text)
    {
        var id = new CSteamID(ulong.Parse(text));
        if (SteamNetworking.GetP2PSessionState(id, out var legacy) && legacy.m_bConnectionActive != 0 && legacy.m_eP2PSessionError == 0) return true;
        var identity = new SteamNetworkingIdentity(); identity.SetSteamID(id);
        return SteamNetworkingMessages.GetSessionConnectionInfo(ref identity, out _, out _)
            == ESteamNetworkingConnectionState.k_ESteamNetworkingConnectionState_Connected;
    }
    internal static bool Connect()
    {
        try
        {
            if (steamReady)
            {
                SteamAPI.RunCallbacks();
                if (SteamUser.BLoggedOn()) return true;
                Disconnect();
            }
            if (library == 0)
            {
                var path = SteamPathResolver.FindNightreignSteamApi();
                if (path is null) return false;
                library = NativeLibrary.Load(path);
            }
            if (!resolverInstalled)
            {
                NativeLibrary.SetDllImportResolver(typeof(SteamAPI).Assembly, (name, _, _) =>
                    name.StartsWith("steam_api64", StringComparison.OrdinalIgnoreCase) ? library : 0);
                resolverInstalled = true;
            }
            Environment.SetEnvironmentVariable("SteamAppId", "2622380");
            Environment.SetEnvironmentVariable("SteamGameId", "2622380");
            steamReady = SteamAPI.Init();
            return steamReady && SteamUser.BLoggedOn();
        }
        catch { return false; }
    }
    internal static void Disconnect()
    {
        try { IdentitySessionCoordinator.Release(ref steamReady, SteamAPI.Shutdown); }
        finally { if (workerStarted) Tick(true); }
    }
    private static void Result(string id, string peer, string resultState, string resultMessage, string code = "")
    {
        try { IdentityFiles.Write(Path.Combine(Root, "results", id + ".json"),
            new { state = resultState, target = peer, transaction = id, message = resultMessage,
                diagnostic_code = code, hold_end_reason = holdEndReason }); }
        catch { } // The durable journal, rather than UI telemetry, owns recovery.
    }
    private static void Set(string next, string detail, bool canBegin = false, string code = "")
    { state = next; message = detail; diagnosticCode = code; Tick(true); }
    private static void Tick() => Tick(false);
    private static void Tick(bool force)
    {
        if (!force && Clock.ElapsedMilliseconds - lastHeartbeat < 750) return;
        lastHeartbeat = Clock.ElapsedMilliseconds;
        try
        {
            IdentityFiles.Write(Path.Combine(Root, "status.json"), new {
                state, target, transaction, message, account, accepts_begin = false, diagnostic_code = diagnosticCode,
                updated_at = DateTimeOffset.UtcNow, worker_pid = supervisorPid,
                task_pid = Environment.ProcessId, task_exiting = workerExiting,
                steam_connected = steamReady, worker_exiting = false, hold_end_reason = holdEndReason,
                steam_lifecycle = matchMode ? "match_hold_v5" : "recovery_only_v3"
            });
        }
        catch { } // Never let a full disk disable the browser/native restore watchdog.
    }
    private static void Sleep(int milliseconds)
    {
        var until = Clock.ElapsedMilliseconds + milliseconds;
        while (Clock.ElapsedMilliseconds < until) { if (steamReady) SteamAPI.RunCallbacks(); Tick(); Thread.Sleep(100); }
    }
}
