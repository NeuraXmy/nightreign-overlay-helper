"""Fallback backend for macOS / Linux, used for development and debugging only."""

from __future__ import annotations

import ctypes
import sys
from typing import Any

from nightreign_overlay.platforms.base import PlatformBackend

_CORE_GRAPHICS = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"


class GenericBackend(PlatformBackend):
    supports_foreground_detection = False

    def __init__(self, name: str) -> None:
        self.name = name
        # Generic backends are development fallbacks. Use a regular topmost window by default because
        # translucent Tool windows can be composited behind other apps on macOS.
        self.supports_transparent_overlay = False

    def has_screen_capture_access(self) -> bool:
        # Without the Screen Recording permission macOS screenshots only contain the wallpaper and
        # this application's own windows.
        check = _core_graphics_function("CGPreflightScreenCaptureAccess")
        return bool(check()) if check is not None else True

    def request_screen_capture_access(self) -> None:
        request = _core_graphics_function("CGRequestScreenCaptureAccess")
        if request is not None:
            request()


def _core_graphics_function(name: str) -> Any | None:
    if sys.platform != "darwin":
        return None
    try:
        function = getattr(ctypes.cdll.LoadLibrary(_CORE_GRAPHICS), name)
    except (OSError, AttributeError):
        return None
    function.argtypes = []
    function.restype = ctypes.c_bool
    return function
