"""Capture backend regression tests without Windows or desktop permissions."""

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEventLoop, QThread, QTimer
from PyQt6.QtGui import QImage

from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.game_window import ForegroundPolicy
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.capture import plugin as capture
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


def _stub_backend(image, closed):
    return lambda *args, **kwargs: SimpleNamespace(
        connect=lambda: None,
        selected_method="test",
        grab=lambda: image,
        close=lambda: closed.append(True),
    )


def test_default_mode_uses_dll_and_switch_releases_backend(plugin, monkeypatch):
    closed = []
    image = QImage(2, 2, QImage.Format.Format_RGB32)
    image.fill(0xFF112233)
    monkeypatch.setattr(capture, "_MaaCapture", _stub_backend(image, closed))
    plugin.on_activate()
    assert plugin.config.mode.value == "auto"
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

        def connect(self):
            pass

        selected_method = "test"

        def grab(self):
            calls.append(("grab", threading.get_ident()))
            return image

        def close(self):
            calls.append(("close", threading.get_ident()))

    monkeypatch.setattr(capture, "_MaaCapture", lambda *args, **kwargs: Backend())
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
        def connect(self):
            pass

        selected_method = "test"

        def grab(self):
            started.set()
            assert release.wait(1)
            return image

        def close(self):
            pass

    monkeypatch.setattr(capture, "_MaaCapture", lambda *args, **kwargs: Backend())
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
        def connect(self):
            pass

        selected_method = "test"

        def grab(self):
            started.set()
            assert release.wait(1)
            return image

        def close(self):
            pass

    monkeypatch.setattr(capture, "_MaaCapture", lambda *args, **kwargs: Backend())
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


@pytest.mark.parametrize(
    "mode,mask", [("auto", 2**64 - 1), ("foreground", 40), ("background", 18), ("gdi", 1), ("screendc", 32)]
)
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


def test_pinned_capture_process_resolves_hwnd_by_process(tmp_path, monkeypatch):
    from nightreign_overlay.plugins.capture import win32

    (tmp_path / "native").mkdir()
    (tmp_path / "native" / "MaaWin32Screencap.dll").touch()
    calls = []

    class FakeManager:
        def __init__(self, path, hwnd, methods):
            calls.append((hwnd, methods))

        def connect(self):
            return True

        def selected_unit_name(self):
            return "gdi"

        def close(self):
            pass

    monkeypatch.setattr(win32, "Manager", FakeManager)
    monkeypatch.setattr(win32, "find_hwnd_by_process", lambda _name: 777)

    def forbidden(title):
        pytest.fail("A pinned capture process must not fall back to title lookup")

    monkeypatch.setattr(win32, "find_window_by_title", forbidden)
    backend = capture._MaaCapture(tmp_path, "gdi", process="RemotePlay.exe")
    backend.connect()
    assert calls == [(777, win32.SCREENCAP_METHOD_MASKS["gdi"])]
    backend.close()


def test_repeated_capture_failures_are_throttled_and_recovery_is_logged(qapp, monkeypatch, caplog):
    import logging

    from nightreign_overlay.plugins.capture import plugin as capture

    clock = [0.0]
    monkeypatch.setattr(capture.time, "monotonic", lambda: clock[0])
    worker = capture._CaptureWorker(Path(), logging.getLogger("test.capture.retries"))
    frames = []
    worker.grabbed.connect(lambda *_args: frames.append(_args[-1]))

    def fail(mode, process):
        raise RuntimeError("game window not found")

    monkeypatch.setattr(worker, "_grab", fail)
    with caplog.at_level(logging.INFO):
        for index in range(100):
            worker.grab(index, 0, "background", "", False)
        assert sum("Capture failed" in message for message in caplog.messages) == 1
        clock[0] = 61
        worker.grab(100, 0, "background", "", False)
        assert sum("Capture failed" in message for message in caplog.messages) == 2
        image = QImage(2, 2, QImage.Format.Format_RGB32)
        image.fill(0)
        monkeypatch.setattr(worker, "_grab", lambda mode, process: image)
        worker.grab(101, 0, "background", "", False)
        assert frames[-1] is not None
        assert "Capture recovered in background mode" in caplog.messages
        monkeypatch.setattr(worker, "_grab", fail)
        worker.grab(102, 0, "background", "", False)
        assert sum("Capture failed" in message for message in caplog.messages) == 3
