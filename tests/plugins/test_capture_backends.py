"""Capture backend regression tests without Windows or desktop permissions."""

import threading
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEventLoop, QPoint, QRect, QThread, QTimer
from PyQt6.QtGui import QImage

from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.game_window import ForegroundPolicy
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.capture import plugin as capture
from nightreign_overlay.plugins.capture.api import crop_rgb, make_frame
from nightreign_overlay.plugins.capture.win32 import Manager


def _request(plugin: capture.CapturePlugin):
    result = []
    loop = QEventLoop()

    def done(frame):
        result.append(frame)
        loop.quit()

    plugin.request_frame(done)
    QTimer.singleShot(1000, loop.quit)
    loop.exec()
    assert result, "capture request timed out"
    return result[0]


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
    callback_thread = []
    result = []
    loop = QEventLoop()

    def done(frame):
        result.append(frame)
        callback_thread.append(QThread.currentThread())
        loop.quit()

    plugin.request_frame(done)
    QTimer.singleShot(1000, loop.quit)
    loop.exec()
    assert result[0].image.pixelColor(0, 0).name() == "#112233"
    assert callback_thread == [QThread.currentThread()]  # Results are delivered on the GUI thread.
    plugin.config.mode.set("foreground")
    QTimer.singleShot(100, loop.quit)
    loop.exec()
    assert closed == [True] and plugin.latest_frame is None
    assert plugin._worker is not None  # Switching does not run native connect until a frame is needed.


def test_backend_lifecycle_is_confined_to_capture_thread(plugin, monkeypatch):
    main_thread = threading.get_ident()
    calls = []
    image = QImage(2, 2, QImage.Format.Format_RGB32)

    class Backend:
        def __init__(self):
            calls.append(("open", threading.get_ident()))

        def grab(self):
            calls.append(("grab", threading.get_ident()))
            return image

        def close(self):
            calls.append(("close", threading.get_ident()))

    monkeypatch.setattr(capture, "_MssCapture", Backend)
    assert _request(plugin) is not None
    plugin.on_deactivate()
    assert [name for name, _ident in calls] == ["open", "grab", "close"]
    assert len({ident for _name, ident in calls}) == 1
    assert calls[0][1] != main_thread


def test_mode_switch_discards_an_in_flight_old_generation(plugin, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    image = QImage(2, 2, QImage.Format.Format_RGB32)

    class Backend:
        def grab(self):
            started.set()
            assert release.wait(1)
            return image

        def close(self):
            pass

    monkeypatch.setattr(capture, "_MssCapture", Backend)
    result = []
    loop = QEventLoop()
    plugin.request_frame(lambda frame: (result.append(frame), loop.quit()))
    assert started.wait(1)
    plugin.config.mode.set("foreground")
    release.set()
    QTimer.singleShot(1000, loop.quit)
    loop.exec()
    assert result == [None]
    assert plugin.latest_frame is None


def test_result_is_discarded_if_detection_becomes_disallowed(plugin, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    image = QImage(2, 2, QImage.Format.Format_RGB32)

    class Backend:
        def grab(self):
            started.set()
            assert release.wait(1)
            return image

        def close(self):
            pass

    monkeypatch.setattr(capture, "_MssCapture", Backend)
    result = []
    loop = QEventLoop()
    plugin.request_frame(lambda frame: (result.append(frame), loop.quit()))
    assert started.wait(1)
    plugin.ctx.services.require(ForegroundPolicy).detection_allowed = False
    release.set()
    QTimer.singleShot(1000, loop.quit)
    loop.exec()
    assert result == [None]
    assert plugin.latest_frame is None


def test_failure_retries_selected_backend_without_desktop_fallback(plugin, monkeypatch):
    attempts = []

    def unavailable(*args):
        attempts.append(args)
        raise RuntimeError("Game not started")

    monkeypatch.setattr(capture, "_MaaCapture", unavailable)
    plugin.config.mode.set("background")
    assert _request(plugin) is None
    assert _request(plugin) is None
    assert len(attempts) == 2


def test_mss_pixels_and_negative_desktop_origin(monkeypatch):
    import mss

    monitor = {"left": -2, "top": -1, "width": 2, "height": 1}
    screenshot = SimpleNamespace(width=2, height=1, bgra=bytes([0x33, 0x22, 0x11, 0, 0x66, 0x55, 0x44, 0]))
    closed = []
    monkeypatch.setattr(
        mss,
        "MSS",
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
