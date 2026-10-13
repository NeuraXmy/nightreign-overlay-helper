"""Public contract for contributing widgets to the shared HUD."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget


class HudApi:
    def add_widget(self, owner: str, widget: QWidget, order: int = 100) -> str:
        """Add a widget and return an opaque token for later removal.

        Optional widget hooks: ``set_hud_scale(scale: float)`` follows the overlay scale, and
        ``set_hud_text_hidden(hidden: bool)`` follows the shared "hide text" setting (hide text labels,
        keep progress bars visible).
        """
        raise NotImplementedError

    def remove_widget(self, token: str) -> None:
        raise NotImplementedError

    def remove_owner(self, owner: str) -> None:
        raise NotImplementedError
