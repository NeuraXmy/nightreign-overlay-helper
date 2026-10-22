"""Ping-ready communication hold; independent native workers own recovery.

No HUD/name recognition. Steam friendship is an exclusion, not evidence of how
the game matched a player. Known friends and ambiguous relationships are excluded.
"""

import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from nightreign_overlay.core.log import get_logger
from nightreign_overlay.core.steam import valid_steam_id

from .block_status import BlockStatusTracker
from .identity_bridge import IdentityBridge

info = get_logger(__name__).info

_RETRYABLE_PREPARATION = {
    "browser_start",
    "page_timeout",
    "page_controls",
    "steam_connect",
    "prepare_cancelled",
}
DEPARTURE_SECONDS = 10
SNAPSHOT_GRACE_SECONDS = 30


class MatchBlockController(QObject):
    statusChanged = pyqtSignal(str)
    peerStatusesChanged = pyqtSignal(object)

    def __init__(self, parent=None, *, bridges=None, legacy=None, clock=time.monotonic):
        super().__init__(parent)
        self.clock = clock
        self.bridges = (
            bridges if bridges is not None else [IdentityBridge(self, slot=0), IdentityBridge(self, slot=1)]
        )
        # Always recover older HUD-version journals too, even with this feature off.
        self.legacy = legacy if legacy is not None else IdentityBridge(self)
        self.enabled = False
        self.account = ""
        self.peers = {}
        self.last_snapshot = float("-inf")
        self.snapshot_valid = False
        self.game_stopped = False
        self.missing_since = {}
        self.attempted = set()
        self.assigned = {}
        self.departed = set()
        self.retry_at = {}
        self.retry_count = {}
        self.message = "disabled"
        self._last_diagnostic = None
        self._ticking = False
        self._block_status = BlockStatusTracker()
        self._peer_statuses = {}
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        for bridge in [self.legacy, *self.bridges]:
            if hasattr(bridge, "changed"):
                bridge.changed.connect(self.tick)

    def start(self):
        for bridge in [self.legacy, *self.bridges]:
            bridge.start()
        self.timer.start()

    def stop(self):
        self.set_enabled(False)
        self.timer.stop()
        for bridge in [self.legacy, *self.bridges]:
            bridge.stop()

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if self.enabled == enabled:
            return
        self.enabled = enabled
        for bridge in self.bridges:
            bridge.set_requests_enabled(enabled)
        if not enabled:
            for bridge in self.bridges:
                bridge.restore()
        self.tick()

    def set_account(self, account):
        account = account if valid_steam_id(account) else ""
        if account == self.account:
            return
        self.account = account
        self.snapshot_valid = False
        self.peers = {}
        self.missing_since.clear()
        self.attempted.clear()
        self.retry_at.clear()
        self.retry_count.clear()
        for bridge in self.bridges:
            bridge.restore()
        self.tick()

    def set_peers(self, peers):
        """Fresh complete native snapshots, including unchanged/empty lists."""
        now = self.clock()
        incoming = {p.steam_id: p for p in peers}
        if not self.snapshot_valid or not 0 <= now - self.last_snapshot <= 5:
            # A resumed Qt event loop may receive this snapshot before the
            # stale-data timer runs. The unseen gap cannot confirm departure.
            self.missing_since.clear()
        for target in self.assigned.values():
            peer = incoming.get(target)
            if peer is not None and peer.state in {"connected", "connecting"}:
                self.missing_since.pop(target, None)
            else:
                self.missing_since.setdefault(target, now)
        # A failed/completed attempt stays suppressed for this continuous presence.
        # Departure permits a new attempt on a future encounter, after recovery.
        self.attempted.intersection_update(set(incoming) | set(self.assigned.values()))
        for target in set(self.retry_at) - set(incoming):
            self.retry_at.pop(target, None)
            self.retry_count.pop(target, None)
        self.peers = incoming
        self.last_snapshot = now
        self.snapshot_valid = True
        self.game_stopped = False
        self.tick()

    def set_status(self, status):
        if status.state == "steam_ready":
            self.game_stopped = False
        if status.state != "steam_ready":
            # Stop new blocks immediately, but a brief helper outage is not
            # proof that an already blocked teammate has left the expedition.
            self.snapshot_valid = False
            self.missing_since.clear()
            if status.state in {"game_exited", "disabled"}:
                self.game_stopped = True
            self.tick()

    def _message(self, value):
        if self.message != value:
            self.message = value
            self.statusChanged.emit(value)

    @property
    def peer_statuses(self):
        """Snapshot keyed by SteamID; independent of mutable worker slots."""
        return dict(self._peer_statuses)

    def _observe_block_status(self, now):
        for index, bridge in [(-1, self.legacy), *enumerate(self.bridges)]:
            self._block_status.observe(
                index, bridge.status, self.assigned.get(index, ""), bridge.pending, now
            )

    def tick(self, *_):
        # Observe durable retry outcomes when Bridge publishes them, before
        # the native worker's next idle heartbeat can overwrite the result.
        if self._ticking:
            return
        self._ticking = True
        try:
            self._tick()
        finally:
            self._ticking = False

    def _tick(self):
        now = self.clock()
        self._observe_block_status(now)
        fresh = self.snapshot_valid and 0 <= now - self.last_snapshot <= 5
        if not fresh:
            self.missing_since.clear()
        for index, target in list(self.assigned.items()):
            bridge = self.bridges[index]
            # Release completed slots before considering departure. Otherwise a
            # departed target's retained transaction ID can re-enter restoration
            # forever and gate every later expedition.
            if bridge.status.get("state") in {"idle", "restored", "error"} and not bridge.pending:
                bridge.authorize_hold("")
                del self.assigned[index]
                if not self.enabled or target not in self.peers or target in self.departed:
                    self.attempted.discard(target)
                    self.retry_at.pop(target, None)
                    self.retry_count.pop(target, None)
                elif (
                    bridge.status.get("state") == "error"
                    and bridge.status.get("diagnostic_code") in _RETRYABLE_PREPARATION
                ) or (
                    bridge.status.get("state") == "restored"
                    and bridge.status.get("diagnostic_code") == "block_unconfirmed"
                ):
                    # A failed/ambiguous POST may retry only after the native
                    # owner has verified and durably committed restoration.
                    count = self.retry_count.get(target, 0) + 1
                    self.retry_count[target] = count
                    self.retry_at[target] = now + min(180, 30 * (2 ** min(count - 1, 3)))
                    info(
                        f"Match name: block retry scheduled slot={index} attempt={count} "
                        f"reason={bridge.status.get('diagnostic_code')}"
                    )
                self.departed.discard(target)
                self.missing_since.pop(target, None)
                info(f"Match name: slot released slot={index} state={bridge.status.get('state')}")
                continue
            peer = self.peers.get(target)
            reason = ""
            if not self.enabled:
                reason = "disabled"
            elif self.game_stopped:
                reason = "game_stopped"
            elif target in self.departed:
                reason = "peer_departed"
            elif peer is not None and peer.relationship in {3, 6}:
                reason = "became_friend"
            elif fresh:
                if peer is None or peer.state not in {"connected", "connecting"}:
                    since = self.missing_since.setdefault(target, now)
                    if self.last_snapshot - since >= DEPARTURE_SECONDS:
                        self.departed.add(target)
                        reason = "peer_departed"
            elif now - self.last_snapshot >= SNAPSHOT_GRACE_SECONDS:
                reason = "snapshot_timeout"
            # A transient empty list, reconnecting session or missing Ping is
            # allowed for existing holds. New blocks still require fresh Ping.
            keep = not reason
            if not keep and bridge.status.get("state") not in {"restoring", "recovery_pending"}:
                info(f"Match name: restore requested slot={index} reason={reason}")
                bridge.restore()
            bridge.authorize_hold(
                target if keep and bridge.status.get("state") in {"preparing", "blocked"} else ""
            )

        # Do not start anything while older recovery is unresolved. Other slots
        # can stay blocked normally; their independent owners cannot starve one
        # another's recovery during a network outage.
        recovering = self.legacy.status.get("state") not in {"idle", "restored"} or any(
            b.status.get("state") in {"restoring", "recovery_pending"} for b in self.bridges
        )
        reason = (
            "disabled"
            if not self.enabled
            else "stale_peers"
            if not fresh
            else "recovery_pending"
            if recovering
            else "ping_ready"
        )
        candidates = []
        if self.enabled and valid_steam_id(self.account) and fresh and not recovering:
            for target, deadline in list(self.retry_at.items()):
                if now >= deadline:
                    self.attempted.discard(target)
                    del self.retry_at[target]
            candidates = [
                p
                for p in self.peers.values()
                if p.relationship == 0
                and p.state == "connected"
                and type(p.ping_ms) is int
                and p.ping_ms >= 0
                and p.steam_id not in self.attempted
            ]
            for peer in candidates:
                available = next(
                    (
                        i
                        for i, b in enumerate(self.bridges)
                        if i not in self.assigned and b.status.get("accepts_begin")
                    ),
                    None,
                )
                if available is None:
                    break
                bridge = self.bridges[available]
                bridge.expected_account = self.account
                bridge.authorize_hold(peer.steam_id)  # publish authorization before request
                if bridge.begin(peer.steam_id):
                    self.assigned[available] = peer.steam_id
                    self.attempted.add(peer.steam_id)
                    info("Match name: nonfriend hold requested")
                else:
                    bridge.authorize_hold("")

        diagnostic = (
            reason,
            len(self.peers),
            sum(p.relationship == 0 for p in self.peers.values()),
            len(candidates),
            len(self.assigned),
        )
        if diagnostic != self._last_diagnostic:
            self._last_diagnostic = diagnostic
            info(
                f"Match name: gate={reason} peers={diagnostic[1]} nonfriends={diagnostic[2]} "
                f"eligible={diagnostic[3]} assigned={diagnostic[4]}"
            )

        states = {b.status.get("state") for b in [self.legacy, *self.bridges]}
        if "recovery_pending" in states:
            message = "recovery_pending"
        elif "restoring" in states:
            message = "restoring"
        elif "blocked" in states:
            message = "blocked"
        elif "preparing" in states:
            message = "preparing"
        elif not self.enabled:
            message = "disabled"
        elif "error" in states:
            message = "retry_wait" if self.retry_at else "error"
        elif not valid_steam_id(self.account):
            message = "account_missing"
        else:
            message = "retry_wait" if self.retry_at else "enabled"
        self._message(message)
        self._observe_block_status(now)
        statuses = self._block_status.snapshot(
            self.peers if not self.game_stopped else {},
            enabled=self.enabled,
            retry_at=self.retry_at,
            fresh=fresh,
            recovering=recovering,
            now=now,
        )
        if statuses != self._peer_statuses:
            self._peer_statuses = statuses
            self.peerStatusesChanged.emit(dict(statuses))
