"""Platform specific functionality behind a common interface."""

from __future__ import annotations

import sys

from nightreign_overlay.platforms.base import PlatformBackend


def create_backend() -> PlatformBackend:
    if sys.platform == "win32":
        from nightreign_overlay.platforms.windows import WindowsBackend

        return WindowsBackend()

    from nightreign_overlay.platforms.generic import GenericBackend

    return GenericBackend("macos" if sys.platform == "darwin" else sys.platform)


__all__ = ["PlatformBackend", "create_backend"]
