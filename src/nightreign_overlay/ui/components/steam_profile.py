"""A stable Steam profile click target that also preserves overlay dragging."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QPoint, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QMouseEvent
from PyQt6.QtWidgets import QApplication, QLabel

from nightreign_overlay.core.steam import profile_uri
from nightreign_overlay.ui.overlay import OverlayWindow


def open_steam_profile(steam_id: str) -> bool:
    uri = profile_uri(steam_id)
    return bool(uri and QDesktopServices.openUrl(QUrl(uri)))


class SteamProfileLabel(QLabel):
    clicked = pyqtSignal(str)

    def __init__(self, steam_id: str, overlay: OverlayWindow, action: Callable[[str], None]) -> None:
        super().__init__(overlay)
        self.steam_id = steam_id
        self.overlay = overlay
        self._press: QPoint | None = None
        self._dragged = False
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Steam must not inherit Qt's mouse grab when the foreground changes.
        self.clicked.connect(action, Qt.ConnectionType.QueuedConnection)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self._press = event.globalPosition().toPoint()
        self._dragged = False
        self.overlay.mousePressEvent(event)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press is not None:
            if (
                event.globalPosition().toPoint() - self._press
            ).manhattanLength() >= QApplication.startDragDistance():
                self._dragged = True
            if self._dragged:
                self.overlay.mouseMoveEvent(event)
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        start, self._press = self._press, None
        self.overlay.mouseReleaseEvent(event)
        if (
            start is not None
            and not self._dragged
            and (event.globalPosition().toPoint() - start).manhattanLength()
            < QApplication.startDragDistance()
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit(self.steam_id)
        event.accept()
