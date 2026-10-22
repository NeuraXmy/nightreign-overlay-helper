"""Independent network status plugin; polling is never gated by frame capture or focus."""

from __future__ import annotations

import sys
from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import BodyLabel, FluentIcon

from nightreign_overlay.core.steam import current_steam_account
from nightreign_overlay.platforms import PlatformBackend
from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.p2p_latency.api import P2PStateChanged, PeerSnapshot
from nightreign_overlay.plugins.p2p_latency.config import P2PConfig, P2POverlayConfig
from nightreign_overlay.plugins.p2p_latency.models import P2PStatus
from nightreign_overlay.plugins.p2p_latency.overlay import P2POverlay
from nightreign_overlay.plugins.p2p_latency.playtime import PlaytimeService
from nightreign_overlay.plugins.p2p_latency.presentation import status_message
from nightreign_overlay.plugins.p2p_latency.service import P2PService
from nightreign_overlay.plugins.steam_recovery.api import RecoveryApi, RecoveryChanged, RecoveryStatus
from nightreign_overlay.ui.components import (
    ConfigRangeCard,
    ConfigSwitchCard,
    OverlaySettingSection,
    SettingSection,
    SettingsPanel,
)
from nightreign_overlay.ui.overlay import OverlayManager


class _PingThresholdCard(ConfigRangeCard):
    def _sync(self, _value: int) -> None:
        # Enforcing warning > good may emit a nested valueChanged. The outer signal
        # still carries the rejected value, so read the final canonical config value.
        super()._sync(self.item.value)


class _StatusLabel(BodyLabel):
    def __init__(self, tr: Callable[..., str], parent: QWidget) -> None:
        super().__init__(parent)
        self._tr = tr
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def set_status(self, status: P2PStatus) -> None:
        tr = self._tr
        helper_ok = status.state not in {"disabled", "helper_missing", "helper_error", "admin_required"}
        steam = (
            "connected"
            if status.state in {"steam_ready", "runtime_error"}
            else ("failed" if status.state == "steam_api_error" else "waiting")
        )
        etw = tr(f"status.etw.{status.etw_state}")
        self.setText(
            tr(
                "status.detail",
                message=status_message(status, tr),
                game=tr("status.running" if status.game_running else "status.waiting"),
                helper=tr("status.running" if helper_ok else "status.stopped"),
                steam=tr(f"status.{steam}"),
                etw=etw,
                count=status.peer_count,
            )
        )
        self.setToolTip(status.message)


class P2PLatencyPlugin(Plugin):
    manifest = PluginManifest(
        id="p2p_latency", kind=PluginKind.FEATURE, icon="WIFI", order=50, requires=("steam_recovery",)
    )
    statusChanged = pyqtSignal(object)
    recoveryChanged = pyqtSignal(object)

    def on_load(self) -> None:
        self.config = self.ctx.config(P2PConfig)
        self.overlay_config = self.ctx.config(P2POverlayConfig, "overlay")
        self.config.enforce_thresholds()
        self.config.good_ping.valueChanged.connect(self.config.enforce_thresholds)
        self.config.warning_ping.valueChanged.connect(self.config.enforce_thresholds)
        self.config.auto_block.valueChanged.connect(self._set_auto_block)
        self._service: P2PService | None = None
        self._window: P2POverlay | None = None
        self._status = P2PStatus("disabled", self.ctx.tr("status.disabled"))

    def on_activate(self) -> None:
        if sys.platform == "win32" and not self.ctx.services.require(PlatformBackend).is_admin():
            message = self.ctx.tr("status.admin_required")
            self._set_status(P2PStatus("admin_required", message, etw_state="error"))
            raise PermissionError(message)
        window = P2POverlay(
            self.ctx.services.require(OverlayManager), self.overlay_config, self.config, self.ctx.tr
        )
        self._window = window
        self.ctx.on_cleanup(window.dispose)
        service = P2PService(self)
        self._service = service
        service.status_changed.connect(window.set_status)
        service.status_changed.connect(self._set_status)
        service.peers_changed.connect(window.set_peers)
        service.snapshotReceived.connect(self._publish_snapshot)
        playtime = PlaytimeService(self)
        service.peers_changed.connect(playtime.set_peers)
        playtime.resultsChanged.connect(window.set_playtimes)
        self.config.show_playtime.valueChanged.connect(playtime.set_enabled)
        playtime.set_enabled(self.config.show_playtime.value)
        self.ctx.on_cleanup(playtime.deleteLater)
        self.ctx.on_cleanup(playtime.stop)
        self.ctx.on_cleanup(lambda: self._stop_service(service))
        self.ctx.subscribe(RecoveryChanged, self._on_recovery)
        self._set_auto_block(self.config.auto_block.value)
        service.start()

    def _stop_service(self, service: P2PService) -> None:
        if recovery := self.ctx.services.get(RecoveryApi):
            recovery.set_enabled(False)
        service.stop()
        service.deleteLater()
        self._service = None
        self._window = None
        self._set_status(P2PStatus("disabled", self.ctx.tr("status.disabled")))

    def _set_status(self, status: P2PStatus) -> None:
        self._status = status
        self.statusChanged.emit(status)
        self.ctx.publish(P2PStateChanged(status))

    def _publish_snapshot(self, peers: tuple) -> None:
        native_account = self._service.account if self._service else ""
        self.ctx.publish(PeerSnapshot(peers, native_account or current_steam_account(), bool(native_account)))

    def _set_auto_block(self, enabled: bool) -> None:
        if recovery := self.ctx.services.get(RecoveryApi):
            recovery.set_enabled(bool(enabled) and self._service is not None)

    def _on_recovery(self, event: RecoveryChanged) -> None:
        self.recoveryChanged.emit(event.status)

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        tr = self.ctx.tr
        panel = SettingsPanel(parent)
        recovery = SettingSection(tr("block.title"))
        recovery.addCard(
            ConfigSwitchCard(self.config.auto_block, FluentIcon.SYNC, tr("block.enable"), tr("block.help"))
        )
        panel.addSection(recovery)
        window = OverlaySettingSection(
            self.overlay_config, tr("settings.window"), include_horizontal_reset=False
        )
        window.addCard(
            ConfigSwitchCard(
                self.config.show_playtime,
                FluentIcon.HISTORY,
                tr("settings.show_playtime"),
                tr("settings.playtime_help"),
            )
        )
        for name in ("good_ping", "warning_ping"):
            window.addCard(
                _PingThresholdCard(
                    self.config.item(name),
                    FluentIcon.SPEED_HIGH,
                    tr(f"settings.{name}"),
                    tr(f"settings.{name}_help"),
                    formatter=lambda value: f"{value} ms",
                )
            )
        status = SettingSection(tr("settings.status"))
        label = _StatusLabel(tr, status)
        label.set_status(self._status)
        self.statusChanged.connect(label.set_status)
        status.addCard(label)
        recovery_label = _RecoveryLabel(tr, status, self.ctx.services)
        self.recoveryChanged.connect(recovery_label.refresh)
        status.addCard(recovery_label)
        if sys.platform == "darwin":
            hint = BodyLabel(tr("settings.simulation"), status)
            hint.setWordWrap(True)
            status.addCard(hint)
        panel.addSection(window)
        panel.addSection(status)
        return panel

    def reset_settings(self) -> None:
        super().reset_settings()
        # A high pre-reset green threshold can temporarily raise the warning threshold.
        self.config.warning_ping.reset()


class _RecoveryLabel(BodyLabel):
    """Also refresh when the latency plugin is disabled but recovery is still running."""

    def __init__(self, tr, parent, services):
        super().__init__(parent)
        from PyQt6.QtCore import QTimer

        self._tr, self._services = tr, services
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self, _value=None):
        recovery = self._services.get(RecoveryApi)
        status = recovery.status if recovery else RecoveryStatus()
        lines = [self._tr("block.summary." + status.state)]
        for peer in status.peers:
            lines.append(f"{peer.name} · {self._tr('block.state.' + peer.state)}")
        self.setText("\n".join(lines))
        self.setToolTip("\n".join(p.detail for p in status.peers if p.detail))
