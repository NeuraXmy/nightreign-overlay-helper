"""Deadly Nightrain countdown: the legacy HP bar colour detector plus a manual toggle."""

from __future__ import annotations

import time
from collections.abc import Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget
from qfluentwidgets import FluentIcon, MessageBox, SettingCard

from nightreign_overlay.core.config import ConfigItem
from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.capture.api import CaptureApi, FrameCaptured
from nightreign_overlay.plugins.hud.api import HudApi, HudTimerBar
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.plugins.rain_timer.config import RainTimerConfig
from nightreign_overlay.plugins.rain_timer.detector import (
    DEFAULT_HLS,
    Hls,
    detect_rain,
    dominant_hls,
    hls_to_rgb,
)
from nightreign_overlay.plugins.region.api import RegionApi, RegionTarget
from nightreign_overlay.ui.components import (
    ConfigRangeCard,
    ConfigSwitchCard,
    HotkeySettingCard,
    SettingSection,
    SettingsPanel,
)

_REGION_KEY = "rain_timer.hp_region"
_TOGGLE = "rain_timer.toggle"
_CALIBRATE_REGION = "rain_timer.calibrate_region"
_CALIBRATE_COLOR = "rain_timer.calibrate_color"
# The legacy app shipped all three shortcuts unbound.
_HOTKEYS = (_TOGGLE, _CALIBRATE_REGION, _CALIBRATE_COLOR)
# Legacy colours of the progress bar and of the selector annotations.
_BAR_COLOR = "#f766ba"
_REGION_COLOR = "#a84747"
_NOT_IN_RAIN_COLOR = "#b83232"
_IN_RAIN_COLOR = "#c03184"
_COLOR_LABEL_STYLE = "background-color: {background}; color: {color}; padding: 2px 6px; border-radius: 4px;"


def _format_period(seconds: int) -> str:
    return f"{max(seconds, 0) // 60}:{max(seconds, 0) % 60:02d}"


def _confirm(parent: QWidget, title: str, content: str) -> bool:
    return bool(MessageBox(title, content, parent.window()).exec())


class _HpColorCard(SettingCard):
    """Legacy "正常血条颜色 / 雨中血条颜色" status of the current image mode, with its reset button."""

    def __init__(self, plugin: RainTimerPlugin, parent: QWidget | None = None) -> None:
        tr = plugin.ctx.tr
        super().__init__(
            FluentIcon.PALETTE, tr("settings.color.status.title"), tr("settings.color.status.content"), parent
        )
        self._plugin = plugin
        self.notInRainLabel = QLabel(self)
        self.inRainLabel = QLabel(self)
        self.resetButton = QPushButton(tr("settings.color.reset"), self)
        self.resetButton.clicked.connect(lambda: plugin._reset_colors(self))
        for caption, label in (
            (tr("settings.color.not_in_rain"), self.notInRainLabel),
            (tr("settings.color.in_rain"), self.inRainLabel),
        ):
            self.hBoxLayout.addWidget(QLabel(caption, self))
            self.hBoxLayout.addSpacing(4)
            self.hBoxLayout.addWidget(label)
            self.hBoxLayout.addSpacing(16)
        self.hBoxLayout.addWidget(self.resetButton)
        self.hBoxLayout.addSpacing(16)
        for hdr in (False, True):
            for in_rain in (False, True):
                plugin._color_item(in_rain, hdr).valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_args: object) -> None:
        # The shared HDR switch lives on another page, so the mode is re-read whenever the card is shown.
        tr = self._plugin.ctx.tr
        hdr = self._plugin._hdr_enabled()
        prefix = tr("settings.color.hdr_prefix") if hdr else ""
        for label, in_rain in ((self.notInRainLabel, False), (self.inRainLabel, True)):
            value = self._plugin._color_item(in_rain, hdr).value
            if value is None:
                label.setText(prefix + tr("settings.color.default"))
                label.setStyleSheet(_COLOR_LABEL_STYLE.format(background="#fff", color="black"))
            else:
                label.setText(prefix + tr("settings.color.set"))
                label.setStyleSheet(
                    _COLOR_LABEL_STYLE.format(background=f"rgb{hls_to_rgb(value)}", color="white")
                )

    def showEvent(self, event: QShowEvent) -> None:
        self.refresh()
        super().showEvent(event)


class RainTimerPlugin(Plugin):
    manifest = PluginManifest(
        id="rain_timer",
        kind=PluginKind.FEATURE,
        icon="CLOUD",
        requires=("capture", "hud", "input", "region"),
        order=10,
    )

    def on_load(self) -> None:
        self.config = self.ctx.config(RainTimerConfig)
        self._started: float | None = None
        self._hud: HudTimerBar | None = None
        self._calibrating = False
        self._clock = QTimer(self)
        self._clock.setInterval(100)
        self._clock.timeout.connect(self._update_timer)

    def on_activate(self) -> None:
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        self.ctx.log.info(
            "In Rain detect enabled: %s, region: %s",
            self.config.auto_detect.value,
            list(region.getRect()) if region else None,
        )
        self._watch_config()
        self.ctx.subscribe(FrameCaptured, self._on_frame)
        capture = self.ctx.services.require(CaptureApi)
        capture.acquire_stream(self.id)
        self.ctx.on_cleanup(lambda: capture.release_stream(self.id))
        self._register_hotkeys(self.ctx.services.require(HotkeyApi))
        self._create_hud(self.ctx.services.require(HudApi))
        self._clock.start()
        self.ctx.on_cleanup(self._clock.stop)

    def on_deactivate(self) -> None:
        self._hud = None

    def _watch_config(self) -> None:
        def on_auto_detect(value: bool) -> None:
            self.ctx.log.info("In Rain detect enabled: %s", value)

        self.config.auto_detect.valueChanged.connect(on_auto_detect)
        self.ctx.on_cleanup(lambda: self.config.auto_detect.valueChanged.disconnect(on_auto_detect))

    def _register_hotkeys(self, hotkeys: HotkeyApi) -> None:
        callbacks = {
            _TOGGLE: self._toggle,
            _CALIBRATE_REGION: self._calibrate_region,
            _CALIBRATE_COLOR: self._calibrate_color,
        }
        for action in _HOTKEYS:
            hotkeys.register(action, HotkeyBinding(None), callbacks[action])
            self.ctx.on_cleanup(lambda action=action: hotkeys.unregister(action))

    def _create_hud(self, hud: HudApi) -> None:
        widget = HudTimerBar(_BAR_COLOR)
        self._hud = widget
        token = hud.add_widget(self.id, widget, order=10)
        self.ctx.on_cleanup(lambda: hud.remove_widget(token))
        # The HUD shows every new widget; an idle countdown hides itself again.
        self._update_timer()

    # -- detection ----------------------------------------------------------------------------

    def _on_frame(self, event: FrameCaptured) -> None:
        if self._calibrating or not self.config.auto_detect.value:
            return
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        if region is None:
            return
        config = self.config
        result = detect_rain(
            event.image,
            region,
            self._colors(False, event.hdr),
            self._colors(True, event.hdr),
            (config.h_tolerance.value, config.l_tolerance.value, config.s_tolerance.value),
            config.min_area_percent.value / 100,
            config.max_area_percent.value / 100,
        )
        if result is None:
            return
        self.ctx.log.debug(
            "RainDetector: cost: %.3fs, not_in_rain_ratio=%.3f, in_rain_ratio=%.3f",
            result.seconds,
            result.not_in_rain_ratio,
            result.in_rain_ratio,
        )
        if result.in_rain is True and self._started is None:
            self._start()
        elif result.in_rain is False and self._started is not None:
            self._stop()

    def _color_item(self, in_rain: bool, hdr: bool) -> ConfigItem[list[int] | None]:
        name = ("in_rain_hls" if in_rain else "not_in_rain_hls") + ("_hdr" if hdr else "")
        return self.config.item(name)

    def _colors(self, in_rain: bool, hdr: bool) -> tuple[Hls, Hls]:
        calibrated = self._color_item(in_rain, hdr).value
        return (calibrated, calibrated) if calibrated is not None else DEFAULT_HLS[(in_rain, hdr)]

    def _hdr_enabled(self) -> bool:
        # Read on demand: the settings page exists before capture is active.
        capture = self.ctx.services.get(CaptureApi)
        return capture is not None and capture.hdr_enabled()

    # -- countdown ----------------------------------------------------------------------------

    def _start(self) -> None:
        self._started = time.monotonic()
        self.ctx.log.info("Started in rain.")
        self._update_timer()

    def _stop(self) -> None:
        self._started = None
        self.ctx.log.info("Stopped in rain.")
        self._update_timer()

    def _toggle(self, source: str = "shortcut") -> None:
        if self._started is None:
            self._start()
            self.ctx.log.info("Started in rain by %s.", source)
        else:
            self._stop()
            self.ctx.log.info("Stopped in rain by %s.", source)

    def _update_timer(self) -> None:
        if self._hud is None:
            return
        if self._started is None:
            self._hud.set_progress(0.0, "")
            return
        # Like the legacy app the countdown is not stopped when it runs out; the bar just hides until
        # the HP bar leaves the rain colour (or the toggle is pressed).
        total = self.config.duration_seconds.value
        elapsed = time.monotonic() - self._started
        progress = 1.0 - min(elapsed / total, 1.0)
        text = self.ctx.tr(
            "hud.text",
            remaining=_format_period(int(max(total - elapsed, 0))),
            percent=int(100 * (1.0 - progress)),
        )
        self._hud.set_progress(progress, text)

    # -- calibration --------------------------------------------------------------------------

    def _calibrate_region(self) -> None:
        """Suspend detection while the full-screen selector has the event loop."""
        if self._calibrating:
            return
        self._calibrating = True
        try:
            self.ctx.services.require(RegionApi).request_region(
                _REGION_KEY, self.ctx.tr("settings.region.annotate"), _REGION_COLOR
            )
        finally:
            self._calibrating = False

    def _calibrate_color(self) -> None:
        """Legacy "校准血条颜色": box the normal and/or in-rain bar on a frozen screen, keep the peak HLS."""
        if self._calibrating:
            return
        self._calibrating = True
        try:
            samples = self.ctx.services.require(RegionApi).request_samples(
                [
                    RegionTarget(
                        "not_in_rain", self.ctx.tr("settings.color.not_in_rain_annotate"), _NOT_IN_RAIN_COLOR
                    ),
                    RegionTarget("in_rain", self.ctx.tr("settings.color.in_rain_annotate"), _IN_RAIN_COLOR),
                ]
            )
        finally:
            self._calibrating = False
        if samples is None:
            self.ctx.log.warning("align hp color setting canceled")
            return
        # Only the colours of the current image mode are replaced.
        hdr = self._hdr_enabled()
        for target, in_rain in (("not_in_rain", False), ("in_rain", True)):
            sample = samples.get(target)
            hls = dominant_hls(sample) if sample is not None else None
            if hls is not None:
                self._color_item(in_rain, hdr).set(hls)
        self._log_colors()

    def _reset_colors(self, parent: QWidget) -> None:
        hdr = self._hdr_enabled()
        mode = self.ctx.tr("settings.color.mode_hdr" if hdr else "settings.color.mode_normal")
        if not _confirm(
            parent,
            self.ctx.tr("settings.color.reset_title"),
            self.ctx.tr("settings.color.reset_confirm", mode=mode),
        ):
            return
        self._color_item(False, hdr).reset()
        self._color_item(True, hdr).reset()
        self._log_colors()

    def _log_colors(self) -> None:
        config = self.config
        self.ctx.log.info(
            "Updated hp color: not_in_rain_hls=%s, in_rain_hls=%s, "
            "not_in_rain_hls_hdr=%s, in_rain_hls_hdr=%s",
            config.not_in_rain_hls.value,
            config.in_rain_hls.value,
            config.not_in_rain_hls_hdr.value,
            config.in_rain_hls_hdr.value,
        )

    # -- settings -----------------------------------------------------------------------------

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        tr = self.ctx.tr
        panel = SettingsPanel(parent)
        hotkeys = self.ctx.services.require(HotkeyApi)

        def hotkey_card(
            action: str, icon: FluentIcon, key: str, callback: Callable[[], None]
        ) -> HotkeySettingCard:
            return HotkeySettingCard(
                hotkeys,
                action,
                HotkeyBinding(None),
                icon,
                tr(f"settings.{key}.title"),
                tr(f"settings.{key}.content"),
                actions=[(tr(f"settings.{key}.button"), callback)],
            )

        basic = SettingSection(tr("settings.basic.title"))
        basic.addCards(
            ConfigSwitchCard(
                self.config.auto_detect,
                FluentIcon.CAMERA,
                tr("settings.auto.title"),
                tr("settings.auto.content"),
            ),
            hotkey_card(_CALIBRATE_REGION, FluentIcon.SYNC, "region", self._calibrate_region),
            hotkey_card(_TOGGLE, FluentIcon.STOP_WATCH, "toggle", lambda: self._toggle("button")),
        )
        color = SettingSection(tr("settings.color.title"))
        color.addCards(
            hotkey_card(_CALIBRATE_COLOR, FluentIcon.BRUSH, "color.calibrate", self._calibrate_color),
            _HpColorCard(self),
        )
        advanced = SettingSection(tr("settings.advanced.title"))
        advanced.addCards(
            ConfigRangeCard(
                self.config.duration_seconds,
                FluentIcon.HISTORY,
                tr("settings.duration.title"),
                formatter=lambda value: f"{value}s",
            ),
            *(
                ConfigRangeCard(
                    self.config.item(name), FluentIcon.DEVELOPER_TOOLS, tr(f"settings.{name}.title")
                )
                for name in ("h_tolerance", "l_tolerance", "s_tolerance")
            ),
            *(
                ConfigRangeCard(
                    self.config.item(name),
                    FluentIcon.DEVELOPER_TOOLS,
                    tr(f"settings.{name}.title"),
                    tr(f"settings.{name}.content"),
                    formatter=lambda value: f"{value}%",
                )
                for name in ("min_area_percent", "max_area_percent")
            ),
        )
        panel.addSection(basic)
        panel.addSection(color)
        panel.addSection(advanced)
        return panel

    def reset_settings(self) -> None:
        super().reset_settings()
        hotkeys = self.ctx.services.require(HotkeyApi)
        for action in _HOTKEYS:
            hotkeys.set_binding(action, HotkeyBinding(None))
        if (regions := self.ctx.services.get(RegionApi)) is not None:
            regions.clear_region(_REGION_KEY)
        self.ctx.log.info("Settings reset to defaults.")
