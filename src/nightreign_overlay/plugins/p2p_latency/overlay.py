"""Legacy widget layout integrated with the shared overlay manager."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QGuiApplication
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QGridLayout, QLabel, QVBoxLayout

from nightreign_overlay.plugins.p2p_latency.config import P2PConfig, P2POverlayConfig
from nightreign_overlay.plugins.p2p_latency.models import P2PPeer, P2PStatus
from nightreign_overlay.plugins.p2p_latency.playtime import PlaytimeResult
from nightreign_overlay.plugins.p2p_latency.presentation import status_message
from nightreign_overlay.ui.components.steam_profile import SteamProfileLabel, open_steam_profile
from nightreign_overlay.ui.overlay import OverlayManager, OverlayWindow


def get_ping_color(ping_ms: int | None, good_ping: int, warning_ping: int) -> str:
    if ping_ms is None:
        return "#b8b8b8"
    if ping_ms < good_ping:
        return "#62d26f"
    if ping_ms < warning_ping:
        return "#f3ca52"
    return "#ff6464"


class P2POverlay(OverlayWindow):
    drag_hint_enabled = True
    position_anchor = "right"
    # Keep player names compact so latency and quality remain visible. This is about 60% of the
    # space the name column previously occupied in the 310 px legacy overlay.
    _NAME_COLUMN_WIDTH = 110
    _BASE_WIDTH = 240

    def __init__(
        self,
        manager: OverlayManager,
        config: P2POverlayConfig,
        metrics_config: P2PConfig,
        tr: Callable[..., str],
    ) -> None:
        self.status = P2PStatus("waiting_for_game", "等待 nightreign.exe")
        self.peers: list[P2PPeer] = []
        self._rows: dict[str, tuple[QLabel, ...]] = {}
        self._playtimes: dict[str, PlaytimeResult] = {}
        self._metrics_config = metrics_config
        self._tr = tr
        super().__init__(manager, config, tr("overlay.title"), QSize(self._BASE_WIDTH, 80))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame(self)
        self.panel.setObjectName("p2pPanel")
        root.addWidget(self.panel)
        self.panel_layout = QVBoxLayout(self.panel)
        self.panel_layout.setSpacing(5)
        self.status_label = QLabel(tr("overlay.waiting"), self.panel)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.panel_layout.addWidget(self.status_label)
        self._add_shadow(self.status_label)
        self.peer_grid = QGridLayout()
        self.peer_grid.setHorizontalSpacing(12)
        self.peer_grid.setVerticalSpacing(3)
        self.panel_layout.addLayout(self.peer_grid)
        metrics_config.good_ping.valueChanged.connect(self._refresh_rows)
        metrics_config.warning_ping.valueChanged.connect(self._refresh_rows)
        metrics_config.show_playtime.valueChanged.connect(self._refresh_rows)
        self.on_scale_changed(self.scale_factor)
        self.show_overlay()

    def should_be_visible(self) -> bool:
        return self.windowOpacity() > 0.01 and super().should_be_visible()

    def set_status(self, status: P2PStatus) -> None:
        self.status = status
        if status.state == "steam_ready" and status.etw_state == "admin_required":
            message = self._tr("status.etw.admin_required")
        elif status.state == "steam_ready" and status.etw_state == "error":
            message = self._tr("status.etw.error")
        elif status.state == "steam_ready":
            message = self._tr("overlay.waiting")
        else:
            message = status_message(status, self._tr)
        self.status_label.setText(message)
        self.status_label.setToolTip(status.message)
        self._refresh_rows()
        self.update_visibility()

    def set_peers(self, peers: list[P2PPeer]) -> None:
        self.peers = list(peers)
        self._refresh_rows()

    def set_playtimes(self, results: dict[str, PlaytimeResult]) -> None:
        self._playtimes = dict(results)
        self._refresh_rows()

    def _open_profile(self, steam_id: str) -> None:
        if (
            not self._disposing
            and self.status.state == "steam_ready"
            and any(p.steam_id == steam_id for p in self.peers)
        ):
            open_steam_profile(steam_id)

    def on_scale_changed(self, scale: float) -> None:
        self.peer_grid.setHorizontalSpacing(max(1, int(12 * scale)))
        self.status_label.setStyleSheet(f"color: white; font-size: {int(13 * scale)}px; font-weight: bold;")
        self.panel_layout.setContentsMargins(
            int(12 * scale), int(9 * scale), int(12 * scale), int(10 * scale)
        )
        self.panel.setStyleSheet("QFrame#p2pPanel { background: transparent; border: none; }")
        self._refresh_rows()

    @staticmethod
    def _add_shadow(label: QLabel) -> None:
        shadow = QGraphicsDropShadowEffect(label)
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 150))
        shadow.setOffset(0, 0)
        label.setGraphicsEffect(shadow)

    def _fit_content(self) -> None:
        self.panel_layout.invalidate()
        base_width = self._BASE_WIDTH + (110 if self._metrics_config.show_playtime.value else 0)
        width = int(base_width * self.scale_factor)
        # The panel's stylesheet border sits outside its layout's margins.
        margins = self.panel.contentsMargins()
        if self.panel_layout.hasHeightForWidth():
            height = self.panel_layout.totalHeightForWidth(width - margins.left() - margins.right())
        else:
            height = self.panel_layout.sizeHint().height()
        height += margins.top() + margins.bottom()
        self.set_base_size(QSize(base_width, max(1, round(height / self.scale_factor))))
        # The legacy widget height comes from its layout, not a rounded base-size scale.
        self.setFixedHeight(max(1, height))
        self.layout().activate()
        self.panel_layout.activate()

    def _apply_size(self) -> None:
        # Truncate width * scale, matching the legacy scaling convention.
        self._resize_preserving_anchor(
            int(self.base_size.width() * self.scale_factor),
            max(1, int(self.base_size.height() * self.scale_factor)),
        )
        self.updateGeometry()
        self.update()

    def _default_position(self) -> QPoint:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QPoint(0, 0)
        rect = screen.availableGeometry()
        return QPoint(rect.right() - self.width() - 24, rect.top() + 100)

    def _clear_grid(self) -> None:
        while self.peer_grid.count():
            self.peer_grid.takeAt(0)

    def _refresh_rows(self, _value: object = None) -> None:
        self._clear_grid()
        show_peers = self.status.state == "steam_ready"
        active = {peer.steam_id for peer in self.peers} if show_peers else set()
        for target in set(self._rows) - active:
            for label in self._rows.pop(target):
                label.hide()
                label.deleteLater()
        etw_warning = self.status.etw_state in {"admin_required", "error"}
        self.status_label.setVisible(not show_peers or not self.peers or etw_warning)
        font_size = int(13 * self.scale_factor)
        for row, peer in enumerate(self.peers if show_peers else []):
            if peer.steam_id not in self._rows:
                labels = (
                    SteamProfileLabel(peer.steam_id, self, self._open_profile),
                    QLabel(self.panel),
                    QLabel(self.panel),
                    QLabel(self.panel),
                )
                for label in labels:
                    self._add_shadow(label)
                self._rows[peer.steam_id] = labels
            name_label, ping_label, quality_label, playtime_label = self._rows[peer.steam_id]
            name_width = max(1, int(self._NAME_COLUMN_WIDTH * self.scale_factor))
            name_label.setFixedWidth(name_width)
            tooltip = f"{peer.name}\nSteamID: {peer.steam_id}\nAPI: {peer.api}"
            tooltip += "\n" + self._tr("overlay.open_profile")
            if peer.api == "legacy" and peer.ping_ms is None:
                tooltip += "\n" + self._tr("overlay.legacy_no_fields")
            elif peer.api == "legacy":
                tooltip += "\n" + self._tr("overlay.etw_source")
            name_label.setToolTip(tooltip)
            name_label.setStyleSheet(f"color: white; font-size: {font_size}px;")
            name_label.ensurePolished()
            name_label.setText(
                QFontMetrics(name_label.font()).elidedText(peer.name, Qt.TextElideMode.ElideRight, name_width)
            )

            ping_text = "-- ms" if peer.ping_ms is None else f"{peer.ping_ms} ms"
            ping_color = get_ping_color(
                peer.ping_ms, self._metrics_config.good_ping.value, self._metrics_config.warning_ping.value
            )
            ping_label.setText(ping_text)
            ping_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            ping_label.setStyleSheet(f"color: {ping_color}; font-size: {font_size}px; font-weight: 600;")

            quality_text = "--" if peer.quality is None else f"{round(peer.quality * 100)}%"
            quality_label.setText(quality_text)
            quality_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            quality_label.setStyleSheet(f"color: #d8d8d8; font-size: {font_size}px;")

            self.peer_grid.addWidget(name_label, row, 0)
            self.peer_grid.addWidget(ping_label, row, 1)
            self.peer_grid.addWidget(quality_label, row, 2)
            if self._metrics_config.show_playtime.value:
                result = self._playtimes.get(peer.steam_id, PlaytimeResult("loading"))
                text = self._tr(f"playtime.{result.state}")
                if result.state == "available" and result.minutes is not None:
                    text = self._tr("playtime.hours", hours=f"{result.minutes / 60:.1f}")
                playtime_label.setText(text)
                playtime_label.setStyleSheet(f"color: #d8d8d8; font-size: {font_size}px;")
                playtime_label.setToolTip(self._tr("settings.playtime_help"))
                playtime_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.peer_grid.addWidget(playtime_label, row, 3)
                playtime_label.show()
            else:
                playtime_label.hide()
            # Newly reparented widgets stay hidden until Qt processes its queued
            # show event. Include them before measuring this fixed-size overlay.
            for label in (name_label, ping_label, quality_label):
                label.ensurePolished()
                label.show()

        self.peer_grid.setColumnStretch(0, 0)
        self._fit_content()
