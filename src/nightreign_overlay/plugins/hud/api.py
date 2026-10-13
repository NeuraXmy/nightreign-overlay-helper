"""Public contract for contributing widgets to the shared HUD."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QProgressBar, QVBoxLayout, QWidget

#: Legacy HUD content width at scale 1.0; every legacy bar spans the whole overlay.
HUD_BASE_WIDTH = 400
_BASE_BAR_HEIGHT = 16
_BASE_FONT_SIZE = 14
_BAR_STYLE = """
    QProgressBar {{
        border: 2px solid #5a5a5a;
        border-radius: {radius}px;
        background-color: rgba(60, 60, 60, 178);
    }}
    QProgressBar::chunk {{ background-color: {color}; }}
"""
_TEXT_STYLE = "color: white; font-weight: bold; font-size: {font_size}px;"


class HudApi:
    def add_widget(self, owner: str, widget: QWidget, order: int = 100) -> str:
        """Add a widget and return an opaque token for later removal.

        Optional widget hooks: ``set_hud_scale(scale: float)`` follows the overlay scale, and
        ``set_hud_text_hidden(hidden: bool)`` follows the shared "hide text" setting (hide text labels,
        keep progress bars visible). A widget may hide and show itself; the HUD re-fits its size.
        """
        raise NotImplementedError

    def remove_widget(self, token: str) -> None:
        raise NotImplementedError

    def remove_owner(self, owner: str) -> None:
        raise NotImplementedError


class HudTimerBar(QWidget):
    """Legacy single countdown bar with a shadowed label below (rain / art timers).

    The whole widget hides while ``progress <= 0``, matching the legacy ``*_progress_visible`` rule.
    """

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self._scale = 1.0
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 10_000)
        self.bar.setTextVisible(False)
        self._layout.addWidget(self.bar)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shadow = QGraphicsDropShadowEffect(self.label)
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 150))
        shadow.setOffset(0, 0)
        self.label.setGraphicsEffect(shadow)
        self._layout.addWidget(self.label)
        self.set_hud_scale(1.0)

    def set_progress(self, progress: float, text: str, color: str | None = None) -> None:
        if color is not None and color != self._color:
            self._color = color
            self._apply_style()
        self.bar.setValue(int(min(max(progress, 0.0), 1.0) * self.bar.maximum()))
        self.label.setText(text)
        self.setVisible(progress > 0.0)

    def set_hud_scale(self, scale: float) -> None:
        self._scale = scale
        self.setFixedWidth(round(HUD_BASE_WIDTH * scale))
        self._layout.setSpacing(round(6 * scale))
        self.bar.setFixedHeight(round(_BASE_BAR_HEIGHT * scale))
        self.label.setStyleSheet(_TEXT_STYLE.format(font_size=round(_BASE_FONT_SIZE * scale)))
        self._apply_style()

    def set_hud_text_hidden(self, hidden: bool) -> None:
        self.label.setHidden(hidden)

    def _apply_style(self) -> None:
        radius = max(1, round(self.bar.height() / 5))
        self.bar.setStyleSheet(_BAR_STYLE.format(radius=radius, color=self._color))
