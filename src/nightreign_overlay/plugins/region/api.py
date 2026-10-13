"""Public contract for selecting and storing screen rectangles."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage


@dataclass(frozen=True)
class RegionTarget:
    """One annotation button of the selector, e.g. "click and box the normal HP bar".

    ``color`` is the button and rectangle colour; ``None`` uses the selector's default colour.
    """

    id: str
    label: str
    color: str | None = None


class RegionApi:
    def request_region(self, key: str, label: str | None = None, color: str | None = None) -> QRect | None:
        """Interactively select one global-pixel rectangle and persist it under ``key``.

        ``label`` is the text of the selector's annotation button, e.g. "click and box the DAY I icon";
        ``color`` overrides the default annotation colour.
        """
        raise NotImplementedError

    def request_samples(self, targets: Sequence[RegionTarget]) -> dict[str, QImage] | None:
        """Freeze the screen, let the user box any of ``targets`` and return the frozen pixels of each box.

        Only boxed targets appear in the result and nothing is persisted. Returns ``None`` when the user
        cancels or the screen cannot be frozen (e.g. missing screen-capture permission).
        """
        raise NotImplementedError

    def region(self, key: str) -> QRect | None:
        raise NotImplementedError

    def save_region_for_test(self, key: str, rect: QRect) -> None:
        """Persist a rectangle without opening the platform UI."""
        raise NotImplementedError
