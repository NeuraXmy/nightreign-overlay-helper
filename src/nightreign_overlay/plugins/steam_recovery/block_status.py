"""Read-only presentation of communication operations; never controls Steam."""

from dataclasses import dataclass, replace

HISTORY_SECONDS = 120
HISTORY_LIMIT = 4


@dataclass(frozen=True)
class PeerBlockStatus:
    steam_id: str
    name: str
    state: str
    text: str
    detail: str = ""
    active: bool = False
    pending: bool = False
    updated_at: float = 0


def block_status_color(state):
    if state in {"blocked", "restored"}:
        return "#78cf91"
    if state in {"failed", "retry_wait", "recovery_pending", "unconfirmed"}:
        return "#f3ca72"
    return "#aebec9"


class BlockStatusTracker:
    """Keep per-target results after a worker slot returns to idle or is reused.

    A blank supervisor heartbeat may continue a previously observed operation,
    but never proves its success. No journals or remote state are read here.
    """

    def __init__(self):
        self.records = {}
        self._seen = {}
        self._owners = {}
        self._completed = {}

    def observe(self, source, status, assigned_target, request_pending, now):
        signature = tuple(
            status.get(k, "") for k in ("state", "target", "transaction", "diagnostic_code", "message")
        )
        if self._seen.get(source) == signature:
            return
        self._seen[source] = signature
        state, target, transaction, code, detail = signature
        previous_owner = self._owners.get(source, "")
        target = target or assigned_target or previous_owner
        if not isinstance(target, str) or len(target) != 17 or not target.isascii() or not target.isdecimal():
            return
        previous = self.records.get(target)
        if state == "idle":
            # Idle is not a verified unblock result. A result that was actually
            # observed remains visible even after its slot has been released.
            if previous and previous.pending and not request_pending:
                self._record(
                    target, "unconfirmed", "恢复待确认", "组件已空闲，尚未收到该队友的解除成功结果", True, now
                )
            return
        # A blank, unassociated component error must not revive a completed
        # target merely because this worker previously handled it.
        if not status.get("target") and not assigned_target and (not previous or not previous.pending):
            return
        if transaction and self._completed.get(source) == transaction and state in {"preparing", "blocked"}:
            return
        self._owners[source] = target
        if state == "preparing":
            # A restarted bridge can report connection preparation with the
            # previous target. It is not evidence of a new block request.
            if not assigned_target and not request_pending and previous and not previous.pending:
                return
            value = (
                ("preparing", "准备屏蔽", True)
                if assigned_target or request_pending
                else ("unconfirmed", "通信待确认", True)
            )
        elif state == "blocked":
            value = ("blocked", "已屏蔽", True)
        elif state == "restoring":
            value = ("restoring", "解除中", True)
        elif state == "recovery_pending":
            value = ("recovery_pending", "恢复待重试", True)
        elif state == "restored":
            value = (
                ("failed", "屏蔽未完成 · 已解除", False)
                if code == "block_unconfirmed"
                else ("restored", "已解除", False)
            )
        elif state == "error":
            if code == "page_preblocked":
                value = ("preblocked", "原有屏蔽 · 不解除", False)
            elif code == "relationship_excluded":
                value = ("relationship_skipped", "关系不符 · 已跳过", False)
            elif request_pending:
                value = ("unconfirmed", "恢复待确认", True)
            else:
                value = ("failed", "屏蔽未完成", False)
        else:
            return
        if state in {"restored", "error"} and not value[2] and transaction:
            self._completed[source] = transaction
        display_state, text, pending = value
        self._record(target, display_state, text, detail, pending, now)

    def _record(self, target, state, text, detail, pending, now):
        previous = self.records.get(target)
        self.records[target] = PeerBlockStatus(
            target, previous.name if previous else target, state, text, detail, False, pending, now
        )

    def snapshot(self, peers, *, enabled, retry_at, fresh, recovering, now):
        result = {}
        for target, peer in peers.items():
            record = self.records.get(target)
            if record:
                # Names belong to SteamID, never the worker slot.
                record = replace(record, name=peer.name, active=True)
                self.records[target] = record
                if record.state == "failed" and target in retry_at and enabled and peer.relationship == 0:
                    record = replace(record, state="retry_wait", text="失败待重试")
                result[target] = record
            elif enabled:
                if peer.relationship in {3, 6}:
                    state, text = "friend_skipped", "好友跳过"
                elif peer.relationship == 5:
                    state, text = "preblocked", "原有屏蔽 · 不解除"
                elif peer.relationship != 0:
                    state, text = "relationship_skipped", "关系未确认 · 已跳过"
                elif not fresh:
                    state, text = "waiting", "等待队友同步"
                elif peer.state != "connected" or type(peer.ping_ms) is not int or peer.ping_ms < 0:
                    state, text = "waiting", "等待有效延迟"
                elif recovering:
                    state, text = "waiting", "等待其他恢复完成"
                else:
                    state, text = "waiting", "等待屏蔽组件"
                result[target] = PeerBlockStatus(target, peer.name, state, text, active=True)

        absent = sorted(
            (r for target, r in self.records.items() if target not in peers),
            key=lambda r: r.updated_at,
            reverse=True,
        )
        retained = 0
        for record in absent:
            if record.pending or (now - record.updated_at < HISTORY_SECONDS and retained < HISTORY_LIMIT):
                result[record.steam_id] = replace(record, active=False)
                if not record.pending:
                    retained += 1
            else:
                del self.records[record.steam_id]
        return result
