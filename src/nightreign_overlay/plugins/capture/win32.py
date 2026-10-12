"""Small, dependency-free MaaWin32Screencap binding used only on Windows."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


class _ImageBuffer(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.POINTER(ctypes.c_ubyte)),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("channels", ctypes.c_int32),
        ("step", ctypes.c_int32),
    ]


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    channels: int
    step: int
    data: bytes


class Manager:
    """Owns a MaaWSManager handle and copies native pixels before the next capture."""

    METHOD_ALL = (1 << 64) - 1

    def __init__(self, dll_dir: Path, hwnd: int | None) -> None:
        dll_path = dll_dir / "MaaWin32Screencap.dll"
        self._dll = ctypes.CDLL(str(dll_path))
        self._configure_api()
        self._handle = self._dll.MaaWSManagerCreate(hwnd or 0, self.METHOD_ALL)
        if not self._handle:
            raise RuntimeError("MaaWSManagerCreate failed")

    def _configure_api(self) -> None:
        self._dll.MaaWSManagerCreate.restype = ctypes.c_void_p
        self._dll.MaaWSManagerCreate.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        self._dll.MaaWSManagerDestroy.argtypes = [ctypes.c_void_p]
        self._dll.MaaWSManagerConnect.restype = ctypes.c_ubyte
        self._dll.MaaWSManagerConnect.argtypes = [ctypes.c_void_p]
        self._dll.MaaWSManagerInactive.argtypes = [ctypes.c_void_p]
        self._dll.MaaWSManagerScreencap.restype = ctypes.c_ubyte
        self._dll.MaaWSManagerScreencap.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ImageBuffer)]

    def connect(self) -> bool:
        return bool(self._dll.MaaWSManagerConnect(self._handle))

    def screencap(self) -> ImageInfo | None:
        buffer = _ImageBuffer()
        if not self._dll.MaaWSManagerScreencap(self._handle, ctypes.byref(buffer)):
            return None
        row_size = buffer.step if buffer.step > 0 else buffer.width * buffer.channels
        if not buffer.data or buffer.width <= 0 or buffer.height <= 0:
            return None
        data = ctypes.string_at(buffer.data, row_size * buffer.height)
        return ImageInfo(buffer.width, buffer.height, buffer.channels, row_size, data)

    def close(self) -> None:
        if not self._handle:
            return
        try:
            self._dll.MaaWSManagerInactive(self._handle)
        finally:
            self._dll.MaaWSManagerDestroy(self._handle)
            self._handle = None


def find_window_by_title(title: str) -> int | None:
    """Find the first top-level window whose title contains ``title``."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    matches: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if title.casefold() in buffer.value.casefold():
                matches.append(int(hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return matches[0] if matches else None
