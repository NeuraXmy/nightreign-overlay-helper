"""Shared capture with legacy mss, two DLL modes, and a Qt development fallback."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QPoint, QTimer
from PyQt6.QtGui import QGuiApplication, QImage
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.core.game_window import ForegroundPolicy
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


class _CaptureService(CaptureApi):
    def __init__(self, plugin: CapturePlugin) -> None:
        self._plugin = plugin

    def latest_frame(self) -> FrameCaptured | None:
        return self._plugin.latest_frame

    def capture_now(self) -> FrameCaptured | None:
        return self._plugin.capture_now()

    def acquire_stream(self, owner: str) -> None:
        self._plugin.acquire_stream(owner)

    def release_stream(self, owner: str) -> None:
        self._plugin.release_stream(owner)

    def hdr_enabled(self) -> bool:
        return self._plugin.config.hdr_processing.value


class CapturePlugin(Plugin):
    manifest = PluginManifest(
        id="capture",
        kind=PluginKind.INFRASTRUCTURE,
        icon="CAMERA",
        settings_scope=SettingsScope.GENERAL,
        order=0,
    )

    def on_load(self) -> None:
        self.config = self.ctx.config(CaptureConfig)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._capture_stream_tick)
        self.config.interval_ms.valueChanged.connect(self._timer.setInterval)
        self.config.hdr_processing.valueChanged.connect(
            lambda value: self.ctx.log.info("HDR image processing enabled: %s", value)
        )
        self._latest_frame: FrameCaptured | None = None
        self._native: _MaaCapture | None = None
        self._mss: _MssCapture | None = None
        self.config.mode.valueChanged.connect(self._on_mode_changed)
        self._stream_owners: dict[str, int] = {}

    @property
    def latest_frame(self) -> FrameCaptured | None:
        return self._latest_frame

    def on_activate(self) -> None:
        self.ctx.provide(CaptureApi, _CaptureService(self))
        self.ctx.on_cleanup(self._stop_stream)

    def on_deactivate(self) -> None:
        self._stop_stream()
        self._close_backend()

    def _on_mode_changed(self, mode: str) -> None:
        self._close_backend()
        self.ctx.log.info("Capture mode changed to %s", mode)

    def _close_backend(self) -> None:
        self._latest_frame = None
        if self._native is not None:
            self._native.close()
            self._native = None
        if self._mss is not None:
            self._mss.close()
            self._mss = None

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
        if self._stream_owners:
            self.capture_now()

    def _stop_stream(self) -> None:
        self._timer.stop()
        self._stream_owners.clear()

    def capture_now(self) -> FrameCaptured | None:
        # Legacy "仅在游戏时显示和检测": no detection while the game is in the background.
        if not self.ctx.services.require(ForegroundPolicy).detection_allowed:
            return None
        try:
            image = self._grab()
        except Exception:
            self.ctx.log.exception("Capture failed in %s mode; will retry", self.config.mode.value)
            self._close_backend()
            return None
        if image is None or image.isNull():
            return None
        frame = make_frame(image, hdr=self.config.hdr_processing.value)
        self._latest_frame = frame
        self.ctx.publish(frame)
        return frame

    def _grab(self) -> QImage | None:
        if sys.platform != "win32":
            return _grab_primary_screen()
        if self.config.mode.value == "legacy":
            if self._mss is None:
                self._mss = _MssCapture()
                self.ctx.log.info("Capture backend: legacy (mss)")
            return self._mss.grab()
        if self._native is None:
            native = _MaaCapture(self.ctx.root_dir, self.config.mode.value)
            native.connect()
            self._native = native
            self.ctx.log.info("Capture backend: %s (%s)", self.config.mode.value, native.selected_method)
        image = self._native.grab()
        if image is None:
            self._close_backend()
        return image

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


def _grab_primary_screen() -> QImage | None:
    screen = QGuiApplication.primaryScreen()
    return screen.grabWindow(0).toImage() if screen is not None else None


class _MaaCapture:
    """Minimal ctypes bridge for the MaaWin32Screencap manager used by the legacy application."""

    def __init__(self, plugin_dir: Path, mode: str) -> None:
        self._plugin_dir = plugin_dir
        self._mode = mode
        self.selected_method: str | None = None
        self._manager: object | None = None

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

    def grab(self) -> QImage | None:
        if self._manager is None:
            return None
        info = self._manager.screencap()  # type: ignore[union-attr]
        if info is None or info.channels not in (3, 4):
            return None
        image_format = QImage.Format.Format_BGR888 if info.channels == 3 else QImage.Format.Format_ARGB32
        image = QImage(info.data, info.width, info.height, info.step, image_format)
        return image.copy()

    def close(self) -> None:
        if self._manager is not None:
            self._manager.close()  # type: ignore[union-attr]
            self._manager = None


class _MssCapture:
    """Legacy desktop capture, with no game-window operations or WGC sessions.

    Capture the virtual desktop once for all consumers. QImage.offset stores its physical origin so
    calibrated global rectangles work on monitors left of or above the primary monitor as well.
    Creation, grabbing and closing all run on the capture plugin's Qt thread (mss is thread-local).
    """

    def __init__(self) -> None:
        from mss import mss

        self._sct = mss()

    def grab(self) -> QImage:
        monitor = self._sct.monitors[0]
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

    def close(self) -> None:
        self._sct.close()
