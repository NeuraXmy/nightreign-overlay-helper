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

    METHOD_FOREGROUND = (1 << 3) | (1 << 5)
    METHOD_BACKGROUND = (1 << 1) | (1 << 4)

    def __init__(self, dll_dir: Path, hwnd: int, methods: int) -> None:
        dll_path = dll_dir / "MaaWin32Screencap.dll"
        self._dll = ctypes.CDLL(str(dll_path))
        self._configure_api()
        self._handle = self._dll.MaaWSManagerCreate(hwnd, methods)
        if not self._handle:
            raise RuntimeError("MaaWSManagerCreate failed")

    def _configure_api(self) -> None:
        self._dll.MaaWSManagerCreate.restype = ctypes.c_void_p
        self._dll.MaaWSManagerCreate.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        self._dll.MaaWSManagerDestroy.argtypes = [ctypes.c_void_p]
        self._dll.MaaWSManagerDestroy.restype = None
        self._dll.MaaWSManagerConnect.restype = ctypes.c_ubyte
        self._dll.MaaWSManagerConnect.argtypes = [ctypes.c_void_p]
        self._dll.MaaWSManagerInactive.argtypes = [ctypes.c_void_p]
        self._dll.MaaWSManagerInactive.restype = None
        self._dll.MaaWSManagerScreencap.restype = ctypes.c_ubyte
        self._dll.MaaWSManagerScreencap.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ImageBuffer)]
        self._dll.MaaWSManagerSelectedUnitName.restype = ctypes.c_char_p
        self._dll.MaaWSManagerSelectedUnitName.argtypes = [ctypes.c_void_p]

    def selected_unit_name(self) -> str | None:
        name = self._dll.MaaWSManagerSelectedUnitName(self._handle)
        return name.decode("utf-8") if name else None

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
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
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

    user32.EnumWindows.argtypes = [type(callback), wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows(callback, 0)
    return matches[0] if matches else None


def client_geometry(hwnd: int | None) -> tuple[int, int, int, int]:
    """Client bounds in native desktop pixels, including negative multi-monitor origins.

    Scope DPI awareness to this call, restoring the capture thread's previous context afterwards.
    Qt normally enables per-monitor awareness already; the explicit scope also covers embedded callers.
    """
    if hwnd is None:
        raise RuntimeError("Capture window is not connected")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    set_context = getattr(user32, "SetThreadDpiAwarenessContext", None)
    previous = None
    if set_context is not None:
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = ctypes.c_void_p
        previous = set_context(ctypes.c_void_p(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    try:
        rect = wintypes.RECT()
        origin = wintypes.POINT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)) or not user32.ClientToScreen(
            hwnd, ctypes.byref(origin)
        ):
            raise OSError("Cannot query capture window's client geometry")
        return origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top
    finally:
        if previous:
            set_context(previous)
