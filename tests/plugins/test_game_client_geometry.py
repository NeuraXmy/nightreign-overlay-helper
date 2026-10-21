"""Game window discovery uses OS geometry/process identity and never creates a capture backend."""

import ctypes
from types import SimpleNamespace

import pytest

from nightreign_overlay.plugins.capture import plugin as capture
from nightreign_overlay.plugins.capture import win32
from nightreign_overlay.plugins.capture.api import CaptureApi
from tests.support.feature_fakes import FeatureServices


@pytest.mark.parametrize(
    "visible,minimized,executable,opened,query_ok,expected",
    [
        (True, False, r"D:\Steam\nightreign.exe", True, True, True),
        (True, False, r"D:\Steam\NIGHTREIGN.EXE", True, True, True),
        (True, False, r"C:\Browser\chrome.exe", True, True, False),
        (False, False, r"D:\Steam\nightreign.exe", True, True, False),
        (True, True, r"D:\Steam\nightreign.exe", True, True, False),
        (True, False, r"D:\Steam\nightreign.exe", False, True, False),
        (True, False, r"D:\Steam\nightreign.exe", True, False, False),
    ],
)
def test_only_the_visible_game_process_is_accepted(
    monkeypatch, visible, minimized, executable, opened, query_ok, expected
):
    access, closed = [], []

    def get_pid(_hwnd, target):
        ctypes.cast(target, ctypes.POINTER(win32.wintypes.DWORD)).contents.value = 123
        return 1

    def open_process(rights, inherit, pid):
        access.append((rights, inherit, pid))
        return 456 if opened else 0

    def query(_handle, _flags, buffer, _size):
        buffer.value = executable
        return query_ok

    user32 = SimpleNamespace(
        IsWindowVisible=lambda _hwnd: visible,
        IsIconic=lambda _hwnd: minimized,
        GetWindowThreadProcessId=get_pid,
    )
    kernel32 = SimpleNamespace(
        OpenProcess=open_process,
        QueryFullProcessImageNameW=query,
        CloseHandle=lambda handle: closed.append(handle),
    )
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda name, **_kwargs: user32 if name == "user32" else kernel32, raising=False
    )
    assert win32._is_game_window(100) is expected
    assert access == ([(0x1000, False, 123)] if visible and not minimized else [])
    assert closed == ([456] if visible and not minimized and opened else [])


def test_locator_tracks_current_geometry_and_retries_missing_or_recreated_game(monkeypatch):
    now = [10.0]
    hwnd = [None]
    valid = [True]
    geometry = [(-2560, -200, 2560, 1440)]
    searches = []

    def find(title, accept):
        searches.append(title)
        return hwnd[0] if hwnd[0] is not None and accept(hwnd[0]) else None

    monkeypatch.setattr(win32.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(win32, "find_window_by_title", find)
    monkeypatch.setattr(win32, "_is_game_window", lambda candidate: candidate == hwnd[0] and valid[0])
    monkeypatch.setattr(win32, "client_geometry", lambda _hwnd: geometry[0])
    locator = win32.GameClientLocator()
    assert locator.geometry() is None
    assert locator.geometry() is None and len(searches) == 1
    hwnd[0] = 20
    now[0] += 1.1
    assert locator.geometry() == geometry[0]
    geometry[0] = (100, 200, 1920, 1080)
    assert locator.geometry() == geometry[0] and len(searches) == 2
    valid[0] = False  # Minimized, closed or no longer a game window.
    assert locator.geometry() is None
    now[0] += 1.1
    valid[0], hwnd[0] = True, 30
    assert locator.geometry() == geometry[0]

    def fail(_hwnd):
        raise OSError("window disappeared")

    monkeypatch.setattr(win32, "client_geometry", fail)
    assert locator.geometry() is None


@pytest.mark.parametrize("mode", ["legacy", "foreground", "background"])
def test_capture_service_exposes_geometry_without_starting_capture(store, tmp_path, monkeypatch, mode):
    fakes = FeatureServices(store, tmp_path)
    fakes.services.unregister(CaptureApi)
    plugin = capture.CapturePlugin(fakes.context("capture", tmp_path))
    plugin.on_load()
    plugin.config.mode.set(mode)
    plugin.on_activate()
    monkeypatch.setattr(capture, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(
        win32, "GameClientLocator", lambda: SimpleNamespace(geometry=lambda: (-1920, 30, 1920, 1080))
    )
    try:
        api = fakes.services.require(CaptureApi)
        assert api.game_client_rect().getRect() == (-1920, 30, 1920, 1080)
        assert api.latest_frame() is None
        assert plugin._worker is None and not plugin._timer.isActive()
        monkeypatch.setattr(capture, "sys", SimpleNamespace(platform="darwin"))
        assert api.game_client_rect() is None
    finally:
        plugin.on_deactivate()
        plugin.ctx.release()
        fakes.input.ctx.release()
