"""Region calibration plugin with a deliberately small, single-rectangle selection UI."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QPixmap
from PyQt6.QtWidgets import QDialog

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest, SettingsScope
from nightreign_overlay.plugins.region.api import RegionApi
from nightreign_overlay.plugins.region.config import RegionConfig


class _RegionService(RegionApi):
    def __init__(self, plugin: RegionPlugin) -> None:
        self._plugin = plugin

    def request_region(self, key: str) -> QRect | None:
        window = _SelectionDialog(self._plugin.ctx.tr("selection.hint"))
        if window.exec() != QDialog.DialogCode.Accepted or window.selected is None:
            return None
        self.save_region_for_test(key, window.selected)
        return window.selected

    def region(self, key: str) -> QRect | None:
        value = self._plugin.config.regions.value.get(key)
        return QRect(*value) if value is not None else None

    def save_region_for_test(self, key: str, rect: QRect) -> None:
        if rect.width() <= 0 or rect.height() <= 0:
            raise ValueError("a calibrated region must have a positive size")
        region_value = [rect.x(), rect.y(), rect.width(), rect.height()]
        regions = {**self._plugin.config.regions.value, key: region_value}
        self._plugin.config.regions.set(regions)


class RegionPlugin(Plugin):
    manifest = PluginManifest(
        id="region",
        kind=PluginKind.INFRASTRUCTURE,
        icon="CROP",
        settings_scope=SettingsScope.HIDDEN,
        order=20,
    )

    def on_load(self) -> None:
        self.config = self.ctx.config(RegionConfig)

    def on_activate(self) -> None:
        self.ctx.provide(RegionApi, _RegionService(self))


class _SelectionDialog(QDialog):
    """Full-screen selector that returns a global-coordinate rectangle on drag release."""

    def __init__(self, hint: str) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setCursor(Qt.CursorShape.CrossCursor)
        screen = self.screen()
        self._screen_geometry = screen.geometry() if screen is not None else QRect()
        self._pixmap: QPixmap | None = screen.grabWindow(0) if screen is not None else None
        self.setGeometry(self._screen_geometry)
        self.setWindowTitle(hint)
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self.selected: QRect | None = None

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        if self._pixmap is not None:
            painter.drawPixmap(self.rect(), self._pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if self._start is not None and self._current is not None:
            rect = QRect(self._start, self._current).normalized()
            if self._pixmap is not None:
                painter.drawPixmap(rect, self._pixmap, rect)
            painter.setPen(QPen(QColor("#c8a35a"), 2))
            painter.drawRect(rect)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._current = self._start
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        rect = QRect(self._start, event.position().toPoint()).normalized()
        if rect.width() > 4 and rect.height() > 4:
            self.selected = rect.translated(self._screen_geometry.topLeft())
            self.accept()
        else:
            self._start = None
            self._current = None
            self.update()

    def keyPressEvent(self, event: object) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
