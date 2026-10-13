"""Widget-based implementation of the shared HUD overlay."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import count

from PyQt6.QtCore import QEvent, QObject, QSize, Qt
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
        # OverlayWindow initialization applies window mode and queries visibility immediately.
        self._config = config
        super().__init__(manager, overlay_config, title, QSize(1, 1))
        self._entries: dict[str, _Entry] = {}
        self._counter = count()
        self._layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._apply_layout()
        config.enabled.valueChanged.connect(lambda _value: self.update_visibility())
        config.hide_text.valueChanged.connect(self._apply_text_hidden)

    def add_widget(self, owner: str, widget: QWidget, order: int) -> str:
        token = f"{owner}:{next(self._counter)}"
        self._entries[token] = _Entry(owner, order, widget)
        # A layout cannot calculate a reliable size hint for a hidden child on every platform.
        widget.setParent(self)
        set_scale = getattr(widget, "set_hud_scale", None)
        if callable(set_scale):
            set_scale(self.scale_factor)
        _set_text_hidden(widget, self._config.hide_text.value)
        widget.show()
        # Contributed widgets may hide while idle (rain / art bars); the overlay re-fits around them.
        widget.installEventFilter(self)
        self._apply_layout()
        self.show_overlay()
        self.raise_()
        return token

    def remove_widget(self, token: str) -> None:
        entry = self._entries.pop(token, None)
        if entry is not None:
            entry.widget.removeEventFilter(self)
            self._layout.removeWidget(entry.widget)
            entry.widget.setParent(None)
            entry.widget.deleteLater()
            self._apply_layout()

    def remove_owner(self, owner: str) -> None:
        for token in [token for token, entry in self._entries.items() if entry.owner == owner]:
            self.remove_widget(token)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if (
            event is not None
            and event.type() in (QEvent.Type.ShowToParent, QEvent.Type.HideToParent)
            and any(entry.widget is watched for entry in self._entries.values())
        ):
            self._apply_layout()
        return super().eventFilter(watched, event)

    def should_be_visible(self) -> bool:
        return self._config.enabled.value and super().should_be_visible()

    def on_scale_changed(self, scale: float) -> None:
        """Scale contributed QWidget content as well as the top-level overlay window."""
        for entry in self._entries.values():
            set_scale = getattr(entry.widget, "set_hud_scale", None)
            if callable(set_scale):
                set_scale(scale)
        self._apply_layout()

    def _apply_text_hidden(self, hidden: bool) -> None:
        for entry in self._entries.values():
            _set_text_hidden(entry.widget, hidden)
        self._apply_layout()

    def _apply_layout(self) -> None:
        scale = self.scale_factor
        self._layout.setDirection(QBoxLayout.Direction.TopToBottom)
        self._layout.setContentsMargins(*(round(8 * scale) for _ in range(4)))
        self._layout.setSpacing(round(8 * scale))
        while self._layout.count():
            self._layout.takeAt(0)
        for entry in sorted(self._entries.values(), key=lambda entry: entry.order):
            self._layout.addWidget(entry.widget, alignment=Qt.AlignmentFlag.AlignCenter)
        self._layout.activate()
        physical_hint = self._layout.sizeHint().expandedTo(QSize(1, 1))
        logical_hint = QSize(
            max(1, round(physical_hint.width() / scale)),
            max(1, round(physical_hint.height() / scale)),
        )
        self.set_base_size(logical_hint)
        self.updateGeometry()
        self.update()


def _set_text_hidden(widget: QWidget, hidden: bool) -> None:
    set_hidden = getattr(widget, "set_hud_text_hidden", None)
    if callable(set_hidden):
        set_hidden(hidden)
