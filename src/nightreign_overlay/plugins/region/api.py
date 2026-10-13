"""Public contract for selecting and storing screen rectangles."""

from __future__ import annotations

from PyQt6.QtCore import QRect


class RegionApi:
    def request_region(self, key: str, label: str | None = None) -> QRect | None:
        """Interactively select one global-pixel rectangle and persist it under ``key``.

        ``label`` is the text of the selector's annotation button, e.g. "click and box the DAY I icon".
        """
        raise NotImplementedError

    def region(self, key: str) -> QRect | None:
        raise NotImplementedError

    def save_region_for_test(self, key: str, rect: QRect) -> None:
        """Persist a rectangle without opening the platform UI."""
        raise NotImplementedError
