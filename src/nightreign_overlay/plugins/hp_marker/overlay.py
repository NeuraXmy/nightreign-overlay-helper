"""Independent HP markers with logical drawing sizes and physical capture coordinates."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPaintEvent, QPolygonF
from PyQt6.QtWidgets import QWidget

from nightreign_overlay.core.screens import mapping_for_rect
from nightreign_overlay.plugins.hp_marker.config import HpMarkerConfig
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayManager, OverlayWindow


class _WedgeMarker(QWidget):
    """A flat, blunt top tapering to a downward tip on a transparent background."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.color = QColor("#ffffff")

    def set_color(self, color: str) -> None:
        value = QColor(color)
        if value != self.color:
            self.color = value
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        width, height = self.width(), self.height()
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(0, 0),
                    QPointF(width, 0),
                    QPointF(width, height * 0.3),
                    QPointF(width / 2, height),
                    QPointF(0, height * 0.3),
                ]
            )
        )


class HpMarkerOverlay(OverlayWindow):
    def __init__(
        self, manager: OverlayManager, window: OverlayConfig, config: HpMarkerConfig, title: str
    ) -> None:
        self._config = config
        self._region: QRect | None = None
        super().__init__(manager, window, title, QSize(10, 7))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lines = [_WedgeMarker(self) for _ in range(3)]
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @property
    def scale_factor(self) -> float:
        # Markers track physical HP pixels; generic overlay scaling must not move them.
        return 1.0

    def apply_window_mode(self) -> None:
        super().apply_window_mode()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        self.update_visibility()

    def _save_position(self) -> None:
        # Geometry follows detection and is never a draggable, persisted position.
        pass

    def _on_position_changed(self, _value: list[int | None] | None) -> None:
        pass

    def set_hp_region(self, region: QRect) -> None:
        self._region = QRect(region)
        self._tick()
        self.show_overlay()

    def _tick(self) -> None:
        if self._region is None:
            return
        rect = self._region
        logical = mapping_for_rect(rect, QGuiApplication.screens()).to_logical(rect, truncate=True)
        x, y, width = logical.x(), logical.y(), logical.width()
        # Capture coordinates need conversion; marker appearance uses Qt logical
        # pixels so Qt scales it consistently on Retina and other high-DPI screens.
        size = self._config.marker_size.value / 100
        line_height = max(1, int(self._config.line_height.value * size))
        line_width = max(1, int(self._config.line_width.value * size))
        self.setFixedSize(width, line_height)
        self._move_to(QPoint(x, y - line_height))
        positions = (
            int(width * self._config.hpbar_low_hp_marker.value) - line_width // 2,
            int(width * self._config.hpbar_high_hp_marker.value) - line_width // 2,
            width - line_width,
        )
        for line, position in zip(self.lines, positions, strict=True):
            line.setGeometry(position, 0, line_width, line_height)
            line.set_color(self._config.marker_color.value)
        self.update_visibility()

    def dispose(self) -> None:
        self._timer.stop()
        super().dispose()
