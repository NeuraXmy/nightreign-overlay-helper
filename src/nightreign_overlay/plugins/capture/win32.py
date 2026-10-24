"""Small, dependency-free MaaWin32Screencap binding used only on Windows."""

from __future__ import annotations

import ctypes
import enum
import os
import time
from collections.abc import Callable
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


class ScreencapMethod(enum.IntFlag):
    """Concrete capture methods, keyed by their MaaWin32Screencap bitmask values."""

    GDI = 1 << 0
    FRAMEPOOL = 1 << 1
    DXGI_DESKTOP_DUP = 1 << 2
    DXGI_DESKTOP_DUP_WINDOW = 1 << 3
    PRINTWINDOW = 1 << 4
    SCREENDC = 1 << 5


#: All builtin methods, for automatic speed-test selection.
METHOD_ALL = (1 << 64) - 1

#: Capture mode key -> method bitmask. A single concrete method pins the capture
#: method (the speed test has exactly one candidate); see ``CaptureConfig.mode``.
SCREENCAP_METHOD_MASKS: dict[str, int] = {
    "auto": METHOD_ALL,
    "foreground": int(ScreencapMethod.DXGI_DESKTOP_DUP_WINDOW | ScreencapMethod.SCREENDC),
    "background": int(ScreencapMethod.FRAMEPOOL | ScreencapMethod.PRINTWINDOW),
    "gdi": int(ScreencapMethod.GDI),
    "framepool": int(ScreencapMethod.FRAMEPOOL),
    "dxgi_desktop_dup": int(ScreencapMethod.DXGI_DESKTOP_DUP),
    "dxgi_desktop_dup_window": int(ScreencapMethod.DXGI_DESKTOP_DUP_WINDOW),
    "printwindow": int(ScreencapMethod.PRINTWINDOW),
    "screendc": int(ScreencapMethod.SCREENDC),
}


class Manager:
    """Owns a MaaWSManager handle and copies native pixels before the next capture."""

    METHOD_FOREGROUND = SCREENCAP_METHOD_MASKS["foreground"]
    METHOD_BACKGROUND = SCREENCAP_METHOD_MASKS["background"]

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


def find_window_by_title(title: str, accept: Callable[[int], bool] | None = None) -> int | None:
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
            if title.casefold() in buffer.value.casefold() and (accept is None or accept(int(hwnd))):
                matches.append(int(hwnd))
        return True

    user32.EnumWindows.argtypes = [type(callback), wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows(callback, 0)
    return matches[0] if matches else None


def _configure_process_apis() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    """Declare process-query signatures (handles must be pointer-sized) and return the DLLs."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return user32, kernel32


def _process_image_name(pid: int) -> str | None:
    """Executable file name of ``pid`` (``None`` without permission or when it exited)."""
    _user32, kernel32 = _configure_process_apis()
    process = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return None
    try:
        size = wintypes.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
            return None
        return path.value.replace("\\", "/").rsplit("/", 1)[-1]
    finally:
        kernel32.CloseHandle(process)


def _window_pid(hwnd: int) -> int:
    user32, _kernel32 = _configure_process_apis()
    pid = wintypes.DWORD()
    if not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        return 0
    return int(pid.value)


def _is_game_window(hwnd: int) -> bool:
    """Only accept a visible, non-minimized window owned by nightreign.exe.

    Querying the executable path uses limited process information, never game memory or Steam APIs.
    A browser/Steam page with the game title must not be used as a HUD reference.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    for name in ("IsWindowVisible", "IsIconic"):
        function = getattr(user32, name)
        function.argtypes = [wintypes.HWND]
        function.restype = wintypes.BOOL
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return False
    pid = _window_pid(hwnd)
    if not pid:
        return False
    image = _process_image_name(pid)
    return image is not None and image.casefold() == "nightreign.exe"


def list_window_processes() -> list[tuple[str, str]]:
    """Enumerate processes owning a visible top-level window as ``(title, image name)``.

    One window per process (the topmost one), skipping tool windows and this process, sorted by
    image name — the source of the manual capture-process picker (e.g. PS Remote Play streaming).
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    current_pid = os.getpid()
    windows: dict[int, tuple[str, str]] = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        pid = _window_pid(hwnd)
        if not pid or pid == current_pid or pid in windows:
            return True
        if not user32.IsWindowVisible(hwnd) or user32.GetWindowLongW(hwnd, -20) & 0x00000080:
            return True  # WS_EX_TOOLWINDOW
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        image = _process_image_name(pid) or ""
        windows[pid] = (buffer.value, image)
        return True

    user32.EnumWindows.argtypes = [type(callback), wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows(callback, 0)
    return sorted(windows.values(), key=lambda entry: (entry[1].casefold(), entry[0].casefold()))


def find_hwnd_by_process(image_name: str) -> int | None:
    """Find the visible top-level window of ``image_name`` (case-insensitive).

    EnumWindows returns windows in Z order, so the foreground window of the streaming app wins.
    Used when the game itself does not run on this PC (e.g. PS5 remote play).
    """
    target = image_name.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if not target:
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    current_pid = os.getpid()
    matches: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        if matches:
            return False
        if not user32.IsWindowVisible(hwnd) or user32.GetWindowLongW(hwnd, -20) & 0x00000080:
            return True  # hidden or WS_EX_TOOLWINDOW
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        pid = _window_pid(hwnd)
        if not pid or pid == current_pid:
            return True
        name = _process_image_name(pid)
        if name and name.casefold() == target:
            matches.append(int(hwnd))
        return True

    user32.EnumWindows.argtypes = [type(callback), wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows(callback, 0)
    return matches[0] if matches else None


class GameClientLocator:
    """Reuse a validated window handle, but read its current physical geometry on every query."""

    def __init__(self) -> None:
        self._hwnd: int | None = None
        self._next_search = 0.0

    def geometry(self) -> tuple[int, int, int, int] | None:
        try:
            if self._hwnd is not None and not _is_game_window(self._hwnd):
                self._hwnd = None
            if self._hwnd is None:
                now = time.monotonic()
                if now < self._next_search:
                    return None
                self._next_search = now + 1.0
                self._hwnd = find_window_by_title("ELDEN RING NIGHTREIGN", accept=_is_game_window)
                if self._hwnd is None:
                    return None
            rect = client_geometry(self._hwnd)
            # The window may disappear or minimize during the geometry query.
            if rect[2] > 0 and rect[3] > 0 and _is_game_window(self._hwnd):
                return rect
        except (OSError, RuntimeError):
            pass
        self._hwnd = None
        return None


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
