"""Fallback backend for macOS / Linux, used for development and debugging only."""

from __future__ import annotations

import sys

from nightreign_overlay.platforms.base import PlatformBackend


class GenericBackend(PlatformBackend):
    supports_foreground_detection = False

    def __init__(self, name: str) -> None:
        self.name = name
        # Qt renders translucent frameless windows fine on macOS; other platforms depend on the compositor.
        self.supports_transparent_overlay = sys.platform == "darwin"
