"""Capture backend regression tests without Windows or desktop permissions."""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QImage

from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.game_window import ForegroundPolicy
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.capture import plugin as capture
from nightreign_overlay.plugins.capture.api import crop_rgb, make_frame
from nightreign_overlay.plugins.capture.win32 import Manager


@pytest.fixture
def plugin(store, tmp_path, monkeypatch):
    services = ServiceRegistry()
    services.register(ForegroundPolicy, SimpleNamespace(detection_allowed=True))
    plugin = capture.CapturePlugin(
        PluginContext("capture", tmp_path, store, Translator("zh_CN"), services, EventBus())
    )
    plugin.on_load()
    monkeypatch.setattr(capture, "sys", SimpleNamespace(platform="win32"))
    yield plugin
    plugin.on_deactivate()


def test_default_mss_never_initializes_dll_and_switch_releases_backend(plugin, monkeypatch):
    closed = []
    image = QImage(2, 2, QImage.Format.Format_RGB32)
    image.fill(0xFF112233)
    monkeypatch.setattr(
        capture, "_MssCapture", lambda: SimpleNamespace(grab=lambda: image, close=lambda: closed.append(True))
    )

    def forbidden(*args):
        pytest.fail("Default legacy mode must not initialize the DLL")

    monkeypatch.setattr(capture, "_MaaCapture", forbidden)
    plugin.on_activate()
    assert plugin.config.mode.value == "legacy"
    assert plugin.capture_now().image.pixelColor(0, 0).name() == "#112233"
    plugin.config.mode.set("foreground")
    assert closed == [True] and plugin.latest_frame is None
    assert plugin._native is None  # Switching does not run native connect until a frame is needed.


def test_failure_retries_selected_backend_without_desktop_fallback(plugin, monkeypatch):
    attempts = []

    def unavailable(*args):
        attempts.append(args)
        raise RuntimeError("Game not started")

    monkeypatch.setattr(capture, "_MaaCapture", unavailable)
    plugin.config.mode.set("background")
    assert plugin.capture_now() is None
    assert plugin.capture_now() is None
    assert len(attempts) == 2 and plugin._mss is None


def test_mss_pixels_and_negative_desktop_origin(monkeypatch):
    import mss

    monitor = {"left": -2, "top": -1, "width": 2, "height": 1}
    screenshot = SimpleNamespace(width=2, height=1, bgra=bytes([0x33, 0x22, 0x11, 0, 0x66, 0x55, 0x44, 0]))
    closed = []
    monkeypatch.setattr(
        mss,
        "mss",
        lambda: SimpleNamespace(
            monitors=[monitor], grab=lambda region: screenshot, close=lambda: closed.append(True)
        ),
    )
    backend = capture._MssCapture()
    frame = make_frame(backend.grab())
    backend.close()
    assert closed == [True]
    assert frame.image.offset() == QPoint(-2, -1)
    assert frame.image.pixelColor(0, 0).alpha() == 255
    assert crop_rgb(frame.image, QRect(-1, -1, 1, 1)).tolist() == [[[0x44, 0x55, 0x66]]]
    assert crop_rgb(frame.image).shape == (1, 2, 3)


@pytest.mark.parametrize("mode,mask", [("foreground", 40), ("background", 18)])
def test_dll_receives_only_requested_methods(tmp_path, monkeypatch, mode, mask):
    from nightreign_overlay.plugins.capture import win32

    (tmp_path / "native").mkdir()
    (tmp_path / "native" / "MaaWin32Screencap.dll").touch()
    calls = []

    class FakeManager:
        METHOD_FOREGROUND = Manager.METHOD_FOREGROUND
        METHOD_BACKGROUND = Manager.METHOD_BACKGROUND

        def __init__(self, path, hwnd, methods):
            calls.append((hwnd, methods))

        def connect(self):
            return True

        def selected_unit_name(self):
            return "test-method"

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(win32, "Manager", FakeManager)
    monkeypatch.setattr(win32, "find_window_by_title", lambda title: 123)
    backend = capture._MaaCapture(tmp_path, mode)
    backend.connect()
    assert calls == [(123, mask)] and backend.selected_method == "test-method"
    backend.close()
    assert calls[-1] == "closed"
