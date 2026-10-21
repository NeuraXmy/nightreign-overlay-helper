"""A separate, temporary post-expedition overlay with explicit comment buttons."""

from pathlib import Path

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QGuiApplication, QIcon
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QVBoxLayout
from qfluentwidgets import ToolButton

from nightreign_overlay.ui.components.steam_profile import SteamProfileLabel, open_steam_profile
from nightreign_overlay.ui.overlay import OverlayWindow


class CommendationOverlay(OverlayWindow):
    commendClicked = pyqtSignal(str)
    dismissed = pyqtSignal()
    drag_hint_enabled = True

    def __init__(self, manager, config, tr):
        self._tr = tr
        self.rows = []
        self._widgets = {}
        super().__init__(manager, config, tr("overlay.title"), QSize(410, 70))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame(self)
        self.panel.setObjectName("commendationPanel")
        self.panel.setStyleSheet(
            "#commendationPanel { background: rgba(20, 25, 32, 235); border-radius: 8px; }"
        )
        root.addWidget(self.panel)
        self.grid = QGridLayout(self.panel)
        self.title = QLabel(tr("overlay.title"), self.panel)
        self.close_button = QPushButton("×", self.panel)
        self.close_button.setToolTip(tr("settings.dismiss"))
        self.close_button.clicked.connect(self.dismissed)
        self.grid.addWidget(self.title, 0, 0)
        self.grid.addWidget(self.close_button, 0, 1)
        self.on_scale_changed(self.scale_factor)

    def should_be_visible(self) -> bool:
        return bool(self.rows) and super().should_be_visible()

    def _default_position(self) -> QPoint:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QPoint(0, 0)
        rect = screen.availableGeometry()
        return QPoint(rect.center().x() - self.width() // 2, rect.top() + 180)

    def _open_profile(self, target: str) -> None:
        if not self._disposing and any(row["steam_id"] == target for row in self.rows):
            open_steam_profile(target)

    def set_rows(self, rows: list[dict]) -> None:
        self.rows = list(rows)
        active = {row["steam_id"] for row in rows}
        for target in set(self._widgets) - active:
            for widget in self._widgets.pop(target):
                self.grid.removeWidget(widget)
                widget.hide()
                widget.deleteLater()
        for index, row in enumerate(rows):
            target = row["steam_id"]
            if target not in self._widgets:
                name = SteamProfileLabel(target, self, self._open_profile)
                button = ToolButton(QIcon(str(Path(__file__).with_name("thumb-up.svg"))), self.panel)
                button.setToolTip(self._tr("overlay.send"))
                button.clicked.connect(lambda _checked=False, target=target: self.commendClicked.emit(target))
                status = QLabel(self.panel)
                status.setWordWrap(True)
                status.setTextFormat(Qt.TextFormat.PlainText)
                self._widgets[target] = (name, button, status)
            name, button, status = self._widgets[target]
            name.setToolTip(row["name"] + "\n" + self._tr("overlay.open_profile"))
            name.setText(row["name"])
            button.setEnabled(row["enabled"])
            status.setText(self._tr("state." + row["state"]))
            self.grid.addWidget(name, 1 + index * 2, 0)
            self.grid.addWidget(button, 1 + index * 2, 1)
            self.grid.addWidget(status, 2 + index * 2, 0, 1, 2)
            for widget in (name, button, status):
                widget.show()
        self.on_scale_changed(self.scale_factor)
        if rows:
            self.show_overlay()
        else:
            self.hide_overlay()

    def on_scale_changed(self, scale: float) -> None:
        self.grid.setContentsMargins(int(12 * scale), int(8 * scale), int(12 * scale), int(10 * scale))
        self.title.setStyleSheet(f"color: white; font-size: {int(14 * scale)}px; font-weight: bold;")
        self.close_button.setFixedSize(int(34 * scale), int(28 * scale))
        for row in self.rows:
            name, button, status = self._widgets[row["steam_id"]]
            name.setStyleSheet(f"color: #8ec8ff; font-size: {int(15 * scale)}px;")
            name.setFixedWidth(int(300 * scale))
            name.setText(
                QFontMetrics(name.font()).elidedText(row["name"], Qt.TextElideMode.ElideRight, name.width())
            )
            button.setFixedSize(int(48 * scale), int(30 * scale))
            status.setStyleSheet(f"color: #c5cbd3; font-size: {int(12 * scale)}px;")
        self.grid.invalidate()
        height = self.grid.totalHeightForWidth(int(410 * scale))
        self.set_base_size(QSize(410, max(60, round(height / scale))))
