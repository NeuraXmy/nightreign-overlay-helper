"""Capture plugin with a native Windows backend and a Qt development fallback."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication, QImage
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.core.game_window import ForegroundPolicy
from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest, SettingsScope
from nightreign_overlay.plugins.capture.api import CaptureApi, FrameCaptured, make_frame
from nightreign_overlay.plugins.capture.config import CaptureConfig
from nightreign_overlay.ui.components import ConfigRangeCard, ConfigSwitchCard, SettingSection, SettingsPanel


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
        self._stream_owners: dict[str, int] = {}

    @property
    def latest_frame(self) -> FrameCaptured | None:
        return self._latest_frame

    def on_activate(self) -> None:
        if sys.platform == "win32":
            self._native = _MaaCapture(self.ctx.root_dir)
            try:
                self._native.connect()
            except RuntimeError:
                self.ctx.log.exception("MaaWin32Screencap unavailable; using Qt screen capture")
                self._native = None
        self.ctx.provide(CaptureApi, _CaptureService(self))
        self.ctx.on_cleanup(self._stop_stream)

    def on_deactivate(self) -> None:
        self._stop_stream()
        self._latest_frame = None
        if self._native is not None:
            self._native.close()
            self._native = None

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
        image = self._native.grab() if self._native is not None else _grab_primary_screen()
        if image is None or image.isNull():
            return None
        frame = make_frame(image, hdr=self.config.hdr_processing.value)
        self._latest_frame = frame
        self.ctx.publish(frame)
        return frame

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        panel = SettingsPanel(parent)
        section = SettingSection(self.ctx.tr("settings.title"))
        section.addCards(
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

    def __init__(self, plugin_dir: Path) -> None:
        self._plugin_dir = plugin_dir
        self._manager: object | None = None

    def connect(self) -> None:
        from nightreign_overlay.meta import GAME_WINDOW_TITLE
        from nightreign_overlay.plugins.capture.win32 import Manager, find_window_by_title

        dll_dir = self._plugin_dir / "native"
        if not (dll_dir / "MaaWin32Screencap.dll").exists():
            raise RuntimeError(f"MaaWin32Screencap.dll not found in {dll_dir}")
        manager = Manager(dll_dir, find_window_by_title(GAME_WINDOW_TITLE))
        if not manager.connect():
            manager.close()
            raise RuntimeError("MaaWin32Screencap could not connect to the game window")
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
