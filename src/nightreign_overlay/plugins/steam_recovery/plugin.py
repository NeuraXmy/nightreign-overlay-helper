"""Always-available recovery ownership, exposed in the latency feature's page."""

import sys

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest, SettingsScope
from nightreign_overlay.plugins.p2p_latency.api import P2PStateChanged, PeerSnapshot

from .api import RecoveryApi, RecoveryChanged, RecoveryStatus
from .identity_bridge import _read_json
from .match_block import MatchBlockController


class SteamRecoveryPlugin(Plugin, RecoveryApi):
    manifest = PluginManifest(
        id="steam_recovery",
        kind=PluginKind.INFRASTRUCTURE,
        settings_scope=SettingsScope.HIDDEN,
        order=-5,
    )

    def on_load(self) -> None:
        self._controller = None
        self._status = RecoveryStatus()

    def on_activate(self) -> None:
        self.ctx.provide(RecoveryApi, self)
        if sys.platform != "win32":
            self._status = RecoveryStatus("unsupported")
            return
        controller = MatchBlockController(self)
        self._controller = controller
        controller.statusChanged.connect(self._update)
        controller.peerStatusesChanged.connect(self._update)
        self.ctx.subscribe(PeerSnapshot, self._snapshot)
        self.ctx.subscribe(P2PStateChanged, self._connection)
        self.ctx.on_cleanup(self._stop)
        controller.start()
        self._update()

    def _stop(self) -> None:
        if self._controller:
            self._controller.stop()
            self._controller.deleteLater()
            self._controller = None

    def _snapshot(self, event: PeerSnapshot) -> None:
        if self._controller:
            self._controller.set_account(event.account if event.verified_account else "")
            self._controller.set_peers(event.peers)

    def _connection(self, event: P2PStateChanged) -> None:
        if self._controller:
            self._controller.set_status(event.status)

    @property
    def status(self) -> RecoveryStatus:
        return self._status

    def set_enabled(self, enabled: bool) -> None:
        if self._controller:
            self._controller.set_enabled(enabled)

    def pending(self, account: str, target: str) -> bool:
        controller = self._controller
        if not controller:
            return False
        if any(record.steam_id == target and record.pending for record in self._status.peers):
            return True
        # Covers startup before telemetry arrives and journals left by an earlier run.
        for bridge in (controller.legacy, *controller.bridges):
            for path in bridge._root.glob("journal-*.json"):
                record = _read_json(path)
                if record is None:
                    return True
                if (
                    record.get("account") == account
                    and record.get("target") == target
                    and record.get("recovery_needed") is not False
                ):
                    return True
        return False

    def _update(self, *_args) -> None:
        if not self._controller:
            return
        status = RecoveryStatus(self._controller.message, tuple(self._controller.peer_statuses.values()))
        if status != self._status:
            self._status = status
            self.ctx.publish(RecoveryChanged(status))
