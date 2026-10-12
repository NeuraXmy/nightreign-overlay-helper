"""Windows backend implemented with ctypes (no pywin32 dependency)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from nightreign_overlay.core.log import get_logger
from nightreign_overlay.platforms.base import PlatformBackend

log = get_logger(__name__)

_HWND_TOPMOST = wintypes.HWND(-1)
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010

_user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)  # type: ignore[attr-defined]

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
_user32.SetWindowPos.restype = wintypes.BOOL
_shell32.IsUserAnAdmin.restype = wintypes.BOOL


class WindowsBackend(PlatformBackend):
    name = "windows"
    supports_foreground_detection = True
    supports_transparent_overlay = True

    def foreground_window_title(self) -> str | None:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None
        length = _user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def ensure_topmost(self, window_id: int) -> None:
        flags = _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE
        if not _user32.SetWindowPos(wintypes.HWND(window_id), _HWND_TOPMOST, 0, 0, 0, 0, flags):
            log.debug("SetWindowPos(TOPMOST) failed: %d", ctypes.get_last_error())

    def is_admin(self) -> bool:
        try:
            return bool(_shell32.IsUserAnAdmin())
        except OSError:
            return False
