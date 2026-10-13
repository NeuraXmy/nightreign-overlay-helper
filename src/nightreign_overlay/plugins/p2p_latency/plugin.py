"""Independent network status plugin; polling is never gated by frame capture or focus."""

from __future__ import annotations

import sys
from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.p2p_latency.config import P2PConfig, P2POverlayConfig
from nightreign_overlay.plugins.p2p_latency.models import P2PStatus
from nightreign_overlay.plugins.p2p_latency.overlay import P2POverlay
from nightreign_overlay.plugins.p2p_latency.service import P2PService
from nightreign_overlay.ui.components import (
    ConfigRangeCard,
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


class _StatusLabel(QLabel):
    def __init__(self, tr: Callable[..., str], parent: QWidget) -> None:
        super().__init__(parent)
        self._tr = tr
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def set_status(self, status: P2PStatus) -> None:
        tr = self._tr
        helper_ok = status.state not in {"disabled", "helper_missing", "helper_error"}
        steam = (
            "connected"
            if status.state in {"steam_ready", "runtime_error"}
            else ("failed" if status.state == "steam_api_error" else "waiting")
        )
        etw = tr(f"status.etw.{status.etw_state}")
        self.setText(
            tr(
                "status.detail",
                message=status.message,
                game=tr("status.running" if status.game_running else "status.waiting"),
                helper=tr("status.running" if helper_ok else "status.stopped"),
                steam=tr(f"status.{steam}"),
                etw=etw,
                count=status.peer_count,
            )
        )


class P2PLatencyPlugin(Plugin):
    manifest = PluginManifest(id="p2p_latency", kind=PluginKind.FEATURE, icon="WIFI", order=50)
    statusChanged = pyqtSignal(object)

    def on_load(self) -> None:
        self.config = self.ctx.config(P2PConfig)
        self.overlay_config = self.ctx.config(P2POverlayConfig, "overlay")
        self.config.enforce_thresholds()
        self.config.good_ping.valueChanged.connect(self.config.enforce_thresholds)
        self.config.warning_ping.valueChanged.connect(self.config.enforce_thresholds)
        self._service: P2PService | None = None
        self._window: P2POverlay | None = None
        self._status = P2PStatus("disabled", self.ctx.tr("status.disabled"))

    def on_activate(self) -> None:
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
        self.ctx.on_cleanup(lambda: self._stop_service(service))
        service.start()

    def _stop_service(self, service: P2PService) -> None:
        service.stop()
        service.deleteLater()
        self._service = None
        self._window = None
        self._set_status(P2PStatus("disabled", self.ctx.tr("status.disabled")))

    def _set_status(self, status: P2PStatus) -> None:
        self._status = status
        self.statusChanged.emit(status)

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        tr = self.ctx.tr
        panel = SettingsPanel(parent)
        window = OverlaySettingSection(self.overlay_config, tr("settings.window"))
        thresholds = SettingSection(tr("settings.thresholds"))
        for name in ("good_ping", "warning_ping"):
            thresholds.addCard(
                _PingThresholdCard(
                    self.config.item(name),
                    FluentIcon.SPEED_HIGH,
                    tr(f"settings.{name}"),
                    formatter=lambda value: f"{value} ms",
                )
            )
        status = SettingSection(tr("settings.status"))
        label = _StatusLabel(tr, status)
        label.set_status(self._status)
        self.statusChanged.connect(label.set_status)
        status.addCard(label)
        foreground_hint = QLabel(tr("settings.foreground"), status)
        foreground_hint.setWordWrap(True)
        status.addCard(foreground_hint)
        if sys.platform == "darwin":
            hint = QLabel(tr("settings.simulation"), status)
            hint.setWordWrap(True)
            status.addCard(hint)
        panel.addSection(window)
        panel.addSection(thresholds)
        panel.addSection(status)
        return panel

    def reset_settings(self) -> None:
        super().reset_settings()
        # A high pre-reset green threshold can temporarily raise the warning threshold.
        self.config.warning_ping.reset()
