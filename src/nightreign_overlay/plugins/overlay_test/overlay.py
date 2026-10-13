"""The painted test overlay."""

from __future__ import annotations

import time
from collections.abc import Callable

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

from nightreign_overlay.plugins.overlay_test.config import OverlayTestConfig
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayManager, OverlayWindow

BASE_SIZE = QSize(300, 132)
PADDING = 16
REFRESH_INTERVAL_MS = 200

PANEL_COLOR = QColor(18, 18, 22, 215)
TEXT_COLOR = QColor(255, 255, 255)
SECONDARY_TEXT_COLOR = QColor(255, 255, 255, 180)
TRACK_COLOR = QColor(255, 255, 255, 48)
SHADOW_COLOR = QColor(0, 0, 0, 200)


class OverlayTestWindow(OverlayWindow):
    drag_hint_enabled = True

    def __init__(
        self,
        manager: OverlayManager,
        overlay_config: OverlayConfig,
        config: OverlayTestConfig,
        tr: Callable[..., str],
    ) -> None:
        super().__init__(manager, overlay_config, tr("overlay.title"), BASE_SIZE)
        self._config = config
        self._tr = tr
        self._cycle_start = time.monotonic()

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.update)
        self._timer.start()

        config.accent_color.valueChanged.connect(self._repaint)
        config.show_background.valueChanged.connect(self._repaint)
        config.cycle_seconds.valueChanged.connect(self._repaint)

    def restart_countdown(self) -> None:
        self._cycle_start = time.monotonic()
        self.update()

    def remaining_seconds(self) -> float:
        cycle = self._config.cycle_seconds.value
        return cycle - (time.monotonic() - self._cycle_start) % cycle

    def paint_overlay(self, painter: QPainter) -> None:
        width, height = BASE_SIZE.width(), BASE_SIZE.height()
        accent = QColor(self._config.accent_color.value)

        if self._config.show_background.value:
            panel = QPainterPath()
            panel.addRoundedRect(QRectF(0.5, 0.5, width - 1, height - 1), 10, 10)
            painter.fillPath(panel, PANEL_COLOR)
            painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 140), 1))
            painter.drawPath(panel)

        content_width = width - 2 * PADDING
        self._draw_text(
            painter, QRectF(PADDING, 10, content_width, 22), self._tr("overlay.title"), 13, accent, bold=True
        )
        self._draw_text(
            painter,
            QRectF(PADDING, 10, content_width, 22),
            time.strftime("%H:%M:%S"),
            13,
            SECONDARY_TEXT_COLOR,
            align=Qt.AlignmentFlag.AlignRight,
        )

        remaining = self.remaining_seconds()
        self._draw_text(
            painter,
            QRectF(PADDING, 36, content_width, 36),
            self._tr("overlay.countdown", seconds=f"{remaining:.1f}"),
            24,
            TEXT_COLOR,
            bold=True,
        )

        track = QRectF(PADDING, 80, content_width, 8)
        fill = QRectF(
            track.left(), track.top(), track.width() * remaining / self._config.cycle_seconds.value, 8
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(TRACK_COLOR)
        painter.drawRoundedRect(track, 4, 4)
        painter.setBrush(accent)
        painter.drawRoundedRect(fill, 4, 4)

        self._draw_text(
            painter, QRectF(PADDING, 98, content_width, 22), self._status_text(), 11, SECONDARY_TEXT_COLOR
        )

    def _status_text(self) -> str:
        if not self.manager.backend.supports_foreground_detection:
            game = self._tr("overlay.game_unknown")
        elif self.manager.game_foreground:
            game = self._tr("overlay.game_foreground")
        else:
            game = self._tr("overlay.game_background")
        mode = self._tr(
            "overlay.mode_transparent" if self.manager.transparent_mode else "overlay.mode_window"
        )
        return f"{game} · {mode}"

    def _draw_text(
        self,
        painter: QPainter,
        rect: QRectF,
        text: str,
        pixel_size: int,
        color: QColor,
        *,
        bold: bool = False,
        align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    ) -> None:
        font = QFont(self.font())
        font.setPixelSize(pixel_size)
        font.setBold(bold)
        painter.setFont(font)
        flags = align | Qt.AlignmentFlag.AlignVCenter
        # A soft drop shadow keeps text readable without the background panel.
        if not self._config.show_background.value:
            painter.setPen(SHADOW_COLOR)
            painter.drawText(rect.translated(1, 1), flags, text)
        painter.setPen(color)
        painter.drawText(rect, flags, text)

    def _repaint(self, _value: object = None) -> None:
        self.update()
