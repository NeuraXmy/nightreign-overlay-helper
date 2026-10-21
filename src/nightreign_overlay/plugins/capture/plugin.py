"""Shared capture on a dedicated thread: legacy mss, two DLL modes, and a cross-platform mss fallback.

Threading model (the GUI thread never touches a backend, the capture thread never touches plugin state):

* GUI thread — :class:`CapturePlugin`: stream leases, timer, foreground gating, config snapshots, request
  bookkeeping, ``latest_frame`` and publishing :class:`FrameCaptured`.
* Capture thread — :class:`_CaptureWorker`: creates, uses and closes every backend (mss and the Maa DLL are
  bound to the thread that created them) and detaches each image into an immutable frame.

The two sides only talk through queued signals carrying plain values or immutable frames. Every request
carries the plugin's ``generation``; results from an older generation are discarded on mode switch or stop.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.core.game_window import ForegroundPolicy
from nightreign_overlay.core.screens import capture_origin
from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest, SettingsScope
from nightreign_overlay.plugins.capture.api import CaptureApi, FrameCaptured, make_frame
from nightreign_overlay.plugins.capture.config import CaptureConfig
from nightreign_overlay.ui.components import (
    ConfigChoiceCard,
    ConfigRangeCard,
    ConfigSwitchCard,
    SettingSection,
    SettingsPanel,
)

FrameCallback = Callable[[FrameCaptured | None], None]

#: Backend key used off Windows, where the capture mode setting does not apply.
_SCREEN = "screen"
#: How long deactivation waits for an in-flight grab before abandoning the capture thread.
_STOP_TIMEOUT_MS = 3000
#: Threads that did not stop in time; kept referenced so Qt never destroys a running QThread.
_abandoned: list[tuple[QThread, QObject]] = []


class _CaptureService(CaptureApi):
    def __init__(self, plugin: CapturePlugin) -> None:
        self._plugin = plugin

    def latest_frame(self) -> FrameCaptured | None:
        return self._plugin.latest_frame

    def request_frame(self, callback: FrameCallback) -> None:
        self._plugin.request_frame(callback)

    def acquire_stream(self, owner: str) -> None:
        self._plugin.acquire_stream(owner)

    def release_stream(self, owner: str) -> None:
        self._plugin.release_stream(owner)

    def hdr_enabled(self) -> bool:
        return self._plugin.config.hdr_processing.value

    def game_client_rect(self) -> QRect | None:
        return self._plugin.game_client_rect()


class CapturePlugin(Plugin):
    manifest = PluginManifest(
        id="capture",
        kind=PluginKind.INFRASTRUCTURE,
        icon="CAMERA",
        settings_scope=SettingsScope.GENERAL,
        order=0,
    )

    # GUI thread -> capture thread: (request id, generation, mode, hdr).
    _grab_requested = pyqtSignal(int, int, str, bool)
    # GUI thread -> capture thread: release the current backend.
    _close_requested = pyqtSignal()

    def on_load(self) -> None:
        self.config = self.ctx.config(CaptureConfig)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._capture_stream_tick)
        self.config.interval_ms.valueChanged.connect(self._timer.setInterval)
        self.config.hdr_processing.valueChanged.connect(
            lambda value: self.ctx.log.info("HDR image processing enabled: %s", value)
        )
        self._latest_frame: FrameCaptured | None = None
        self.config.mode.valueChanged.connect(self._on_mode_changed)
        self._stream_owners: dict[str, int] = {}
        # All of the following are GUI-thread state only.
        self._thread: QThread | None = None
        self._worker: _CaptureWorker | None = None
        self._generation = 0
        self._last_request = 0
        # The stream keeps at most one grab in flight; ticks arriving meanwhile are dropped.
        self._stream_request: int | None = None
        self._callbacks: dict[int, FrameCallback] = {}
        self._game_window = None

    @property
    def latest_frame(self) -> FrameCaptured | None:
        return self._latest_frame

    def on_activate(self) -> None:
        self.ctx.provide(CaptureApi, _CaptureService(self))
        self.ctx.on_cleanup(self._stop_stream)

    def on_deactivate(self) -> None:
        self._stop_stream()
        self._stop_worker()
        self._game_window = None

    def game_client_rect(self) -> QRect | None:
        if sys.platform != "win32":
            return None
        if self._game_window is None:
            from nightreign_overlay.plugins.capture.win32 import GameClientLocator

            self._game_window = GameClientLocator()
        geometry = self._game_window.geometry()
        return QRect(*geometry) if geometry is not None else None

    def _on_mode_changed(self, mode: str) -> None:
        self._invalidate()
        if self._worker is not None:
            self._close_requested.emit()
        self.ctx.log.info("Capture mode changed to %s", mode)

    def _invalidate(self) -> None:
        """Make every in-flight grab stale; their callbacks receive ``None``."""
        self._generation += 1
        self._stream_request = None
        self._latest_frame = None

    # -- stream ---------------------------------------------------------------------------------

    def acquire_stream(self, owner: str) -> None:
        if not owner:
            raise ValueError("a capture stream owner must not be empty")
        was_idle = not self._stream_owners
        self._stream_owners[owner] = self._stream_owners.get(owner, 0) + 1
        if was_idle:
            self._timer.start(self.config.interval_ms.value)
            # Queue the initial frame so callers can subscribe before it is published.
            QTimer.singleShot(0, self._capture_stream_tick)

    def release_stream(self, owner: str) -> None:
        count = self._stream_owners.get(owner)
        if count is None:
            self.ctx.log.warning("Capture stream released by unknown owner %r", owner)
            return
        if count == 1:
            del self._stream_owners[owner]
        else:
            self._stream_owners[owner] = count - 1
        if not self._stream_owners:
            self._timer.stop()

    def _capture_stream_tick(self) -> None:
        if self._stream_owners and self._stream_request is None:
            self._stream_request = self._request(None)

    def _stop_stream(self) -> None:
        self._timer.stop()
        self._stream_owners.clear()

    # -- requests -------------------------------------------------------------------------------

    def request_frame(self, callback: FrameCallback) -> None:
        self._request(callback)

    def _request(self, callback: FrameCallback | None) -> int | None:
        """Queue one grab on the capture thread; returns its id, or ``None`` when detection is not allowed."""
        self._last_request += 1
        request_id = self._last_request
        if callback is not None:
            self._callbacks[request_id] = callback
        # Legacy "仅在游戏时显示和检测": no detection while the game is in the background.
        if not self.ctx.services.require(ForegroundPolicy).detection_allowed:
            if callback is not None:
                QTimer.singleShot(0, lambda: self._resolve(request_id, None))
            return None
        self._ensure_worker()
        self._grab_requested.emit(
            request_id, self._generation, self.config.mode.value, self.config.hdr_processing.value
        )
        return request_id

    @pyqtSlot(int, int, object)
    def _on_grabbed(self, request_id: int, generation: int, frame: FrameCaptured | None) -> None:
        if request_id == self._stream_request:
            self._stream_request = None
        policy = self.ctx.services.require(ForegroundPolicy)
        if generation != self._generation or not policy.detection_allowed:
            frame = None
        else:
            self._latest_frame = frame
            if frame is not None:
                self.ctx.publish(frame)
        self._resolve(request_id, frame)

    def _resolve(self, request_id: int, frame: FrameCaptured | None) -> None:
        callback = self._callbacks.pop(request_id, None)
        if callback is None:
            return
        try:
            callback(frame)
        except Exception:
            self.ctx.log.exception("Capture callback %r failed", callback)

    # -- capture thread -------------------------------------------------------------------------

    def _ensure_worker(self) -> None:
        if self._worker is not None:
            return
        thread = QThread()
        thread.setObjectName("capture")
        worker = _CaptureWorker(self.ctx.root_dir, self.ctx.log)
        worker.moveToThread(thread)
        queued = Qt.ConnectionType.QueuedConnection
        self._grab_requested.connect(worker.grab, queued)
        self._close_requested.connect(worker.close, queued)
        worker.grabbed.connect(self._on_grabbed, queued)
        # ``finished`` is emitted on the capture thread itself, so backends are closed on their own thread.
        thread.finished.connect(worker.close, Qt.ConnectionType.DirectConnection)
        thread.start()
        self._thread, self._worker = thread, worker

    def _stop_worker(self) -> None:
        self._invalidate()
        self._callbacks.clear()
        thread, worker = self._thread, self._worker
        if thread is None or worker is None:
            return
        self._thread = self._worker = None
        self._grab_requested.disconnect(worker.grab)
        self._close_requested.disconnect(worker.close)
        thread.quit()
        if not thread.wait(_STOP_TIMEOUT_MS):
            self.ctx.log.warning("Capture thread did not stop within %d ms; abandoning it", _STOP_TIMEOUT_MS)
            _abandoned.append((thread, worker))

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        panel = SettingsPanel(parent)
        section = SettingSection(self.ctx.tr("settings.title"))
        section.addCards(
            ConfigChoiceCard(
                self.config.mode,
                [(mode, self.ctx.tr(f"settings.mode.{mode}")) for mode in self.config.mode.option.choices],
                FluentIcon.CAMERA,
                self.ctx.tr("settings.mode.title"),
                self.ctx.tr("settings.mode.content"),
            ),
            ConfigRangeCard(
                self.config.interval_ms,
                FluentIcon.SPEED_HIGH,
                self.ctx.tr("settings.interval.title"),
                self.ctx.tr("settings.interval.content"),
                formatter=lambda value: self.ctx.tr("settings.interval.value", milliseconds=value),
            ),
            ConfigSwitchCard(
                self.config.hdr_processing,
                FluentIcon.BRIGHTNESS,
                self.ctx.tr("settings.hdr.title"),
                self.ctx.tr("settings.hdr.content"),
            ),
        )
        panel.addSection(section)
        return panel


class _CaptureWorker(QObject):
    """Owns the capture backend. Constructed on the GUI thread; every slot then runs on the capture thread."""

    # Capture thread -> GUI thread: (request id, generation, frame or None).
    grabbed = pyqtSignal(int, int, object)

    def __init__(self, root_dir: Path, log: logging.Logger) -> None:
        super().__init__()
        self._root_dir = root_dir
        self._log = log
        self._backend: _MaaCapture | _MssCapture | None = None
        self._backend_key: str | None = None
        self._last_error: tuple[str, type[Exception], str] | None = None
        self._last_error_time = 0.0

    @pyqtSlot(int, int, str, bool)
    def grab(self, request_id: int, generation: int, mode: str, hdr: bool) -> None:
        frame = None
        try:
            image = self._grab(mode)
        except Exception as error:
            signature = (mode, type(error), str(error))
            now = time.monotonic()
            if signature != self._last_error or now - self._last_error_time >= 60:
                self._log.exception(
                    "Capture failed in %s mode; will retry (repeats limited to once/minute)", mode
                )
                self._last_error_time = now
            self._last_error = signature
            self.close()
        else:
            if image is not None and not image.isNull():
                if self._last_error is not None:
                    self._log.info("Capture recovered in %s mode", mode)
                    self._last_error = None
                # Detached copy: nothing on this thread references the frame after it is emitted.
                frame = make_frame(image, hdr=hdr)
        self.grabbed.emit(request_id, generation, frame)

    def _grab(self, mode: str) -> QImage | None:
        key = mode if sys.platform == "win32" else _SCREEN
        if self._backend_key != key:
            self.close()
        if self._backend is None:
            self._backend = self._open(key)
            self._backend_key = key
        image = self._backend.grab()
        if image is None:
            self.close()
        return image

    def _open(self, key: str) -> _MaaCapture | _MssCapture:
        if key == _SCREEN:
            backend = _MssCapture()
            self._log.info("Capture backend: desktop (mss)")
            return backend
        if key == "legacy":
            backend = _MssCapture()
            self._log.info("Capture backend: legacy (mss)")
            return backend
        native = _MaaCapture(self._root_dir, key)
        native.connect()
        self._log.info("Capture backend: %s (%s)", key, native.selected_method)
        return native

    @pyqtSlot()
    def close(self) -> None:
        backend, self._backend, self._backend_key = self._backend, None, None
        if backend is not None:
            try:
                backend.close()
            except Exception:
                self._log.exception("Closing the capture backend failed")


class _MaaCapture:
    """Minimal ctypes bridge for the MaaWin32Screencap manager used by the legacy application."""

    def __init__(self, plugin_dir: Path, mode: str) -> None:
        self._plugin_dir = plugin_dir
        self._mode = mode
        self.selected_method: str | None = None
        self._manager: object | None = None
        self._hwnd: int | None = None

    def connect(self) -> None:
        from nightreign_overlay.meta import GAME_WINDOW_TITLE
        from nightreign_overlay.plugins.capture.win32 import Manager, find_window_by_title

        dll_dir = self._plugin_dir / "native"
        if not (dll_dir / "MaaWin32Screencap.dll").exists():
            raise RuntimeError(f"MaaWin32Screencap.dll not found in {dll_dir}")
        hwnd = find_window_by_title(GAME_WINDOW_TITLE)
        if hwnd is None:
            raise RuntimeError(f"Game window '{GAME_WINDOW_TITLE}' not found")
        methods = Manager.METHOD_FOREGROUND if self._mode == "foreground" else Manager.METHOD_BACKGROUND
        manager = Manager(dll_dir, hwnd, methods)
        try:
            if not manager.connect():
                raise RuntimeError("MaaWin32Screencap could not connect to the game window")
            self.selected_method = manager.selected_unit_name()
        except Exception:
            manager.close()
            raise
        self._manager = manager
        self._hwnd = hwnd

    def grab(self) -> QImage | None:
        if self._manager is None:
            return None
        from nightreign_overlay.plugins.capture.win32 import client_geometry

        before = client_geometry(self._hwnd)
        info = self._manager.screencap()  # type: ignore[union-attr]
        if info is None or info.channels not in (3, 4):
            return None
        after = client_geometry(self._hwnd)
        # A window moving/resizing during a grab has no reliable desktop origin; retry next tick.
        if before != after or after[2] <= 0 or after[3] <= 0:
            return None
        # Desktop/window buffers use BGRX; an unused zero alpha byte must not hide captured pixels.
        image_format = QImage.Format.Format_BGR888 if info.channels == 3 else QImage.Format.Format_RGB32
        image = QImage(info.data, info.width, info.height, info.step, image_format)
        image = image.copy()
        # The DLL captures the client area. Normalize any backend/DPI scaling to native desktop pixels.
        if image.size().width() != after[2] or image.size().height() != after[3]:
            image = image.scaled(after[2], after[3], Qt.AspectRatioMode.IgnoreAspectRatio)
        image.setOffset(QPoint(after[0], after[1]))
        return image

    def close(self) -> None:
        if self._manager is not None:
            self._manager.close()  # type: ignore[union-attr]
            self._manager = None
        self._hwnd = None


class _MssCapture:
    """mss desktop capture, with no game-window operations or WGC sessions.

    By default the virtual desktop is captured once for all consumers (Windows legacy mode). QImage.offset
    stores its physical origin so calibrated global rectangles work on monitors left of or above the primary
    monitor as well. macOS captures each display separately into a non-overlapping native-pixel atlas.
    Creation, grabbing and closing all run on the capture thread (mss instances are thread-bound).
    """

    def __init__(self) -> None:
        import mss

        if sys.platform == "darwin":
            import mss.darwin

            # Physical (Retina) pixels like the calibrated regions; mss defaults to the nominal resolution.
            mss.darwin.IMAGE_OPTIONS &= ~mss.darwin.kCGWindowImageNominalResolution
        # ``MSS`` is the non-deprecated 10.2+ entry point; keep compatibility with mss 10.0/10.1.
        factory = getattr(mss, "MSS", None)
        self._sct = factory() if factory is not None else mss.mss()

    def grab(self) -> QImage:
        if sys.platform == "darwin":
            return self._grab_macos()
        monitor = self._sct.monitors[0]
        return self._grab_monitor(monitor)

    def _grab_monitor(self, monitor: dict) -> QImage:
        screenshot = self._sct.grab(monitor)
        # BGRX: desktop alpha is unused and must not make pixels transparent.
        image = QImage(
            screenshot.bgra,
            screenshot.width,
            screenshot.height,
            screenshot.width * 4,
            QImage.Format.Format_RGB32,
        ).copy()
        image.setOffset(QPoint(monitor["left"], monitor["top"]))
        return image

    def _grab_macos(self) -> QImage:
        # A combined CoreGraphics grab uses one scale for the entire desktop. Grab each display
        # separately instead: mixed Retina / non-Retina screens must keep their native pixels.
        monitors = self._sct.monitors[1:]
        if not monitors:
            raise RuntimeError("No displays available for screen capture")
        images = [(monitor, self._grab_monitor(monitor)) for monitor in monitors]
        ratio = max(
            max(image.width() / monitor["width"], image.height() / monitor["height"])
            for monitor, image in images
        )
        tiles = [
            (capture_origin(QPoint(monitor["left"], monitor["top"]), ratio), image)
            for monitor, image in images
        ]
        if len(tiles) == 1:
            origin, image = tiles[0]
            image.setOffset(origin)
            return image
        bounds = QRect()
        for origin, image in tiles:
            bounds = bounds.united(QRect(origin, image.size()))
        result = QImage(bounds.size(), QImage.Format.Format_RGB32)
        result.fill(Qt.GlobalColor.black)
        painter = QPainter(result)
        try:
            for origin, image in tiles:
                painter.drawImage(origin - bounds.topLeft(), image)
        finally:
            painter.end()
        result.setOffset(bounds.topLeft())
        return result

    def close(self) -> None:
        self._sct.close()
