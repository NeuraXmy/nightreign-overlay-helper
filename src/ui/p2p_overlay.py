from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from src.logger import info
from src.p2p.models import P2PPeer, P2PStatus
from src.ui.utils import set_widget_always_on_top


def get_ping_color(ping_ms: int | None, good_ping: int, warning_ping: int) -> str:
    if ping_ms is None:
        return "#b8b8b8"
    if ping_ms < good_ping:
        return "#62d26f"
    if ping_ms < warning_ping:
        return "#f3ca52"
    return "#ff6464"


@dataclass
class P2POverlayUIState:
    x: int | None = None
    y: int | None = None
    scale: float | None = None
    opacity: float | None = None
    draggable: bool | None = None
    enabled: bool | None = None
    only_show_when_game_foreground: bool | None = None
    is_game_foreground: bool | None = None
    is_menu_opened: bool | None = None
    is_setting_opened: bool | None = None
    good_ping: int | None = None
    warning_ping: int | None = None


class P2POverlayWidget(QWidget):
    right_click_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        set_widget_always_on_top(self)
        self.startTimer(50)

        self.enabled = True
        self.scale = 1.0
        self.good_ping = 80
        self.warning_ping = 150
        self.draggable = False
        self.drag_position = QPoint()
        self.only_show_when_game_foreground = False
        self.is_game_foreground = False
        self.is_menu_opened = False
        self.is_setting_opened = False
        self.status = P2PStatus("waiting_for_game", "等待 nightreign.exe")
        self.peers: list[P2PPeer] = []

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame()
        root_layout.addWidget(self.panel)
        self.panel_layout = QVBoxLayout(self.panel)
        self.panel_layout.setContentsMargins(12, 9, 12, 10)
        self.panel_layout.setSpacing(5)

        self.title_label = QLabel("联机状态 · Ping / 稳定度")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.panel_layout.addWidget(self.title_label)

        self.status_label = QLabel("等待队友 / 等待 Steam 同步")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.panel_layout.addWidget(self.status_label)

        self.legacy_ping_label = QLabel("旧 Steam P2P 接口不提供延迟")
        self.legacy_ping_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.legacy_ping_label.setWordWrap(True)
        self.panel_layout.addWidget(self.legacy_ping_label)

        self.peer_grid = QGridLayout()
        self.peer_grid.setHorizontalSpacing(12)
        self.peer_grid.setVerticalSpacing(3)
        self.panel_layout.addLayout(self.peer_grid)
        self._apply_scale(1.0)
        self.setWindowOpacity(0.75)

    def set_status(self, status: P2PStatus):
        self.status = status
        if status.state in {"steam_api_error", "runtime_error", "helper_error", "helper_missing"}:
            self.status_label.setText(status.message)
        else:
            self.status_label.setText("等待队友 / 等待 Steam 同步")
        self._refresh_rows()

    def set_peers(self, peers: list[P2PPeer]):
        self.peers = list(peers)
        self._refresh_rows()

    def set_game_foreground(self, is_foreground: bool):
        self.update_ui_state(P2POverlayUIState(is_game_foreground=is_foreground))

    def update_ui_state(self, state: P2POverlayUIState):
        if state.x is not None and state.y is not None:
            self.move(state.x, state.y)
        if state.scale is not None:
            self._apply_scale(state.scale)
        if state.opacity is not None:
            self.setWindowOpacity(state.opacity)
        if state.draggable is not None:
            self._set_draggable(state.draggable)
        if state.enabled is not None:
            self.enabled = state.enabled
        if state.only_show_when_game_foreground is not None:
            self.only_show_when_game_foreground = state.only_show_when_game_foreground
        if state.is_game_foreground is not None:
            self.is_game_foreground = state.is_game_foreground
        if state.is_menu_opened is not None:
            self.is_menu_opened = state.is_menu_opened
        if state.is_setting_opened is not None:
            self.is_setting_opened = state.is_setting_opened
        if state.good_ping is not None:
            self.good_ping = state.good_ping
        if state.warning_ping is not None:
            self.warning_ping = state.warning_ping
        self._refresh_rows()

    def mousePressEvent(self, event: QMouseEvent):
        if self.draggable and event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_click_signal.emit()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.draggable and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def timerEvent(self, event):
        visible = self.enabled and self.status.game_running and self.windowOpacity() > 0.01
        if self.only_show_when_game_foreground:
            visible = visible and (self.is_game_foreground or self.is_menu_opened or self.is_setting_opened)
        if visible and not self.isVisible():
            self.show()
        elif not visible and self.isVisible():
            self.hide()

    def _set_draggable(self, draggable: bool):
        self.draggable = draggable
        self._apply_panel_style()
        info(f"P2P overlay draggable: {draggable}")

    def _apply_scale(self, scale: float):
        self.scale = max(0.5, min(2.0, scale))
        self.setFixedWidth(int(310 * self.scale))
        self.title_label.setStyleSheet(
            f"color: white; font-size: {int(15 * self.scale)}px; font-weight: 600;"
        )
        self.status_label.setStyleSheet(
            f"color: #c8c8c8; font-size: {int(13 * self.scale)}px;"
        )
        self.legacy_ping_label.setStyleSheet(
            f"color: #c8a96b; font-size: {int(11 * self.scale)}px;"
        )
        self.panel_layout.setContentsMargins(
            int(12 * self.scale), int(9 * self.scale), int(12 * self.scale), int(10 * self.scale)
        )
        self._apply_panel_style()
        self._refresh_rows()

    def _apply_panel_style(self):
        border = "border: 1px solid rgba(255, 255, 255, 150);" if self.draggable else ""
        self.panel.setStyleSheet(
            "QFrame { background-color: rgba(18, 20, 24, 210); "
            f"border-radius: {int(8 * self.scale)}px; {border} }}"
        )

    def _clear_grid(self):
        while self.peer_grid.count():
            item = self.peer_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _refresh_rows(self):
        self._clear_grid()
        self.status_label.setVisible(not self.peers)
        legacy_ping_unavailable = any(
            peer.api == "legacy" and peer.ping_ms is None for peer in self.peers
        )
        self.legacy_ping_label.setVisible(legacy_ping_unavailable)
        font_size = int(13 * self.scale)
        for row, peer in enumerate(self.peers):
            name_label = QLabel(peer.name)
            tooltip = f"SteamID: {peer.steam_id}\nAPI: {peer.api}"
            if peer.api == "legacy" and peer.ping_ms is None:
                tooltip += "\n旧 Steam P2P 接口没有 Ping/稳定度字段"
            elif peer.api == "legacy":
                tooltip += "\n延迟来源：ETW STUN 往返时间"
            name_label.setToolTip(tooltip)
            name_label.setStyleSheet(f"color: white; font-size: {font_size}px;")

            ping_text = "-- ms" if peer.ping_ms is None else f"{peer.ping_ms} ms"
            ping_color = get_ping_color(peer.ping_ms, self.good_ping, self.warning_ping)
            ping_label = QLabel(ping_text)
            ping_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            ping_label.setStyleSheet(f"color: {ping_color}; font-size: {font_size}px; font-weight: 600;")

            quality_text = "--" if peer.quality is None else f"{round(peer.quality * 100)}%"
            quality_label = QLabel(quality_text)
            quality_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            quality_label.setStyleSheet(f"color: #d8d8d8; font-size: {font_size}px;")

            self.peer_grid.addWidget(name_label, row, 0)
            self.peer_grid.addWidget(ping_label, row, 1)
            self.peer_grid.addWidget(quality_label, row, 2)

        self.peer_grid.setColumnStretch(0, 1)
        self.adjustSize()

    def reset_position(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        self.move(rect.right() - self.width() - 24, rect.top() + 100)
