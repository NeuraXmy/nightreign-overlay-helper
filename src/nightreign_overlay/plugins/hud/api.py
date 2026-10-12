"""Public contract for contributing widgets to the shared HUD."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget


class HudApi:
    def add_widget(self, owner: str, widget: QWidget, order: int = 100) -> str:
        """Add a widget and return an opaque token for later removal."""
        raise NotImplementedError

    def remove_widget(self, token: str) -> None:
        raise NotImplementedError

    def remove_owner(self, owner: str) -> None:
        raise NotImplementedError
