"""Independent HP markers with legacy DPI truncation and 50 ms geometry refresh."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QLabel

from nightreign_overlay.plugins.hp_marker.config import HpMarkerConfig
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayManager, OverlayWindow


class HpMarkerOverlay(OverlayWindow):
    def __init__(
        self, manager: OverlayManager, window: OverlayConfig, config: HpMarkerConfig, title: str
    ) -> None:
        self._config = config
        self._region: QRect | None = None
        super().__init__(manager, window, title, QSize(10, 7))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lines = [QLabel(self) for _ in range(3)]
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
        screen = next(
            (
                s
                for s in QGuiApplication.screens()
                if 0 <= (rect.x() - s.geometry().x()) / s.devicePixelRatio() < s.geometry().width()
                and 0 <= (rect.y() - s.geometry().y()) / s.devicePixelRatio() < s.geometry().height()
            ),
            QGuiApplication.primaryScreen(),
        )
        ratio = screen.devicePixelRatio() if screen is not None else 1.0
        origin = screen.geometry().topLeft() if screen is not None else QPoint()
        x = origin.x() + int((rect.x() - origin.x()) / ratio)
        y = origin.y() + int((rect.y() - origin.y()) / ratio)
        width = int(rect.width() / ratio)
        # Preserve the old truncation (including zero-width lines at very high DPI).
        line_height = int(self._config.line_height.value / self.devicePixelRatio())
        line_width = int(self._config.line_width.value / self.devicePixelRatio())
        self.setFixedSize(width, line_height)
        self._move_to(QPoint(x, y - line_height))
        positions = (
            int(width * self._config.hpbar_low_hp_marker.value) - line_width // 2,
            int(width * self._config.hpbar_high_hp_marker.value) - line_width // 2,
            width - line_width,
        )
        for line, position in zip(self.lines, positions, strict=True):
            line.setGeometry(position, 0, line_width, line_height)
            line.setStyleSheet(f"background-color: {self._config.marker_color.value};")
        self.update_visibility()

    def dispose(self) -> None:
        self._timer.stop()
        super().dispose()
