"""Widget-based implementation of the shared HUD overlay."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import count

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QBoxLayout, QWidget

from nightreign_overlay.plugins.hud.config import HudConfig
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayManager, OverlayWindow


@dataclass
class _Entry:
    owner: str
    order: int
    widget: QWidget


class HudOverlay(OverlayWindow):
    def __init__(
        self,
        manager: OverlayManager,
        overlay_config: OverlayConfig,
        config: HudConfig,
        title: str,
    ) -> None:
        super().__init__(manager, overlay_config, title, QSize(1, 1))
        self._config = config
        self._entries: dict[str, _Entry] = {}
        self._counter = count()
        self._layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._apply_layout()
        config.direction.valueChanged.connect(lambda _value: self._apply_layout())
        config.spacing.valueChanged.connect(lambda _value: self._apply_layout())

    def add_widget(self, owner: str, widget: QWidget, order: int) -> str:
        token = f"{owner}:{next(self._counter)}"
        self._entries[token] = _Entry(owner, order, widget)
        self._apply_layout()
        return token

    def remove_widget(self, token: str) -> None:
        entry = self._entries.pop(token, None)
        if entry is not None:
            self._layout.removeWidget(entry.widget)
            entry.widget.setParent(None)
            entry.widget.deleteLater()
            self._apply_layout()

    def remove_owner(self, owner: str) -> None:
        for token in [token for token, entry in self._entries.items() if entry.owner == owner]:
            self.remove_widget(token)

    def _apply_layout(self) -> None:
        direction = (
            QBoxLayout.Direction.LeftToRight
            if self._config.direction.value == "horizontal"
            else QBoxLayout.Direction.TopToBottom
        )
        self._layout.setDirection(direction)
        self._layout.setSpacing(self._config.spacing.value)
        while self._layout.count():
            self._layout.takeAt(0)
        for entry in sorted(self._entries.values(), key=lambda entry: entry.order):
            self._layout.addWidget(entry.widget, alignment=Qt.AlignmentFlag.AlignCenter)
        hint = self._layout.sizeHint().expandedTo(QSize(1, 1))
        self.set_base_size(hint)
        self.update()
