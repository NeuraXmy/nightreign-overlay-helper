"""DAY I/II/III recognition and the legacy circle countdown state machine."""

from __future__ import annotations

import time
from typing import Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.capture.api import CaptureApi, FrameCaptured
from nightreign_overlay.plugins.day_timer.api import DayPhaseChanged, DayTimerApi, Phase, format_period
from nightreign_overlay.plugins.day_timer.config import DayTimerConfig
from nightreign_overlay.plugins.day_timer.detector import DayDetector
from nightreign_overlay.plugins.hud.api import HudApi
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding, InputDevice
from nightreign_overlay.plugins.region.api import RegionApi
from nightreign_overlay.ui.components import (
    ConfigChoiceCard,
    ConfigRangeCard,
    ConfigSwitchCard,
    HotkeySettingCard,
    MultiButtonSettingCard,
    SettingSection,
    SettingsPanel,
)

_REGION_KEY = "day_timer.detect_region"
# Hits of the same DAY banner within this window refresh the start time instead of starting a new day.
_BANNER_REFRESH_SECONDS = 3.0
_DAY_PROGRESS_STYLE = """
    QProgressBar {{
        border: 2px solid #5a5a5a;
        border-radius: {radius}px;
        background-color: rgba(60, 60, 60, 178);
    }}
    QProgressBar::chunk {{ background-color: #9296cc; }}
"""
_DAY_TEXT_STYLE = "color: white; font-weight: bold; font-size: {font_size}px;"


class _DayTimerHud(QWidget):
    """Legacy-style four-stage circle progress bar with scale-aware child widgets."""

    BASE_WIDTH = 400
    BASE_SEGMENT_HEIGHT = 16
    BASE_FONT_SIZE = 14

    def __init__(self, periods: list[int], waiting_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._segments_layout = QHBoxLayout()
        self._segments: list[QProgressBar] = []
        for duration in periods:
            segment = QProgressBar(self)
            segment.setRange(0, 10_000)
            segment.setTextVisible(False)
            segment.setMinimumWidth(10)
            self._segments.append(segment)
            self._segments_layout.addWidget(segment, duration)
        self._layout.addLayout(self._segments_layout)
        self.label = QLabel(waiting_text, self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shadow = QGraphicsDropShadowEffect(self.label)
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 150))
        shadow.setOffset(0, 0)
        self.label.setGraphicsEffect(shadow)
        self._layout.addWidget(self.label)
        self.set_hud_scale(1.0)

    @property
    def segments(self) -> list[QProgressBar]:
        return self._segments

    def set_hud_scale(self, scale: float) -> None:
        self.setFixedWidth(round(self.BASE_WIDTH * scale))
        self._layout.setSpacing(round(6 * scale))
        self._segments_layout.setSpacing(max(1, round(scale)))
        height = round(self.BASE_SEGMENT_HEIGHT * scale)
        style = _DAY_PROGRESS_STYLE.format(radius=max(1, round(height / 5)))
        for segment in self._segments:
            segment.setFixedHeight(height)
            segment.setStyleSheet(style)
        self.label.setStyleSheet(_DAY_TEXT_STYLE.format(font_size=round(self.BASE_FONT_SIZE * scale)))


class _DayTimerService(DayTimerApi):
    def __init__(self, plugin: DayTimerPlugin) -> None:
        self._plugin = plugin

    def day(self) -> int | None:
        return self._plugin.day

    def phase(self) -> Phase | None:
        return self._plugin.phase


class DayTimerPlugin(Plugin):
    manifest = PluginManifest(
        id="day_timer",
        kind=PluginKind.FEATURE,
        icon="STOP_WATCH",
        requires=("capture", "hud", "input", "region"),
        order=0,
    )

    def on_load(self) -> None:
        self.config = self.ctx.config(DayTimerConfig)
        self.day: int | None = None
        self.phase: Phase | None = None
        self._phase_started: float | None = None
        self._detector: DayDetector | None = None
        self._hud: _DayTimerHud | None = None
        self._progress: list[QProgressBar] = []
        self._label: QLabel | None = None
        self._calibrating = False
        self._clock = QTimer(self)
        self._clock.setInterval(100)
        self._clock.timeout.connect(self._update_timer)

    def on_activate(self) -> None:
        self._detector = DayDetector(self.ctx.resource("templates"))
        self._check_templates(self.config.language.value)
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        self.ctx.log.info(
            "DayX detect enabled: %s, lang: %s, region: %s",
            self.config.auto_detect.value,
            self.config.language.value,
            list(region.getRect()) if region else None,
        )
        self._watch_config()
        self.ctx.provide(DayTimerApi, _DayTimerService(self))
        self.ctx.subscribe(FrameCaptured, self._on_frame)
        capture = self.ctx.services.require(CaptureApi)
        capture.acquire_stream(self.id)
        self.ctx.on_cleanup(lambda: capture.release_stream(self.id))
        self._register_hotkeys(self.ctx.services.require(HotkeyApi))
        self._create_hud(self.ctx.services.require(HudApi))
        self._clock.start()
        self.ctx.on_cleanup(self._clock.stop)

    def on_deactivate(self) -> None:
        self._hud = self._label = None
        self._progress.clear()
        self._detector = None

    def _check_templates(self, language: str) -> None:
        if self._detector is not None and not self._detector.available(language):
            self.ctx.log.error("DAY templates are unavailable for language %s", language)

    def _watch_config(self) -> None:
        def on_language(value: Any) -> None:
            self.ctx.log.info("DayX detect lang changed to %s", value)
            self._check_templates(value)

        watchers = (
            (self.config.auto_detect, lambda value: self.ctx.log.info("DayX detect enabled: %s", value)),
            (self.config.language, on_language),
            (
                self.config.hdr_processing,
                lambda value: self.ctx.log.info("HDR image processing enabled: %s", value),
            ),
        )
        for item, slot in watchers:
            item.valueChanged.connect(slot)
            self.ctx.on_cleanup(lambda item=item, slot=slot: item.valueChanged.disconnect(slot))

    def _register_hotkeys(self, hotkeys: HotkeyApi) -> None:
        hotkeys.register(
            "day_timer.next_day",
            HotkeyBinding(InputDevice.KEYBOARD, ("ctrl", "shift", "d")),
            self._start_next_day,
        )
        hotkeys.register(
            "day_timer.forward",
            HotkeyBinding(InputDevice.KEYBOARD, ("ctrl", "shift", "right")),
            self._forward,
        )
        hotkeys.register(
            "day_timer.backward",
            HotkeyBinding(InputDevice.KEYBOARD, ("ctrl", "shift", "left")),
            self._backward,
        )
        hotkeys.register(
            "day_timer.calibrate_region",
            HotkeyBinding(None),
            self._calibrate_region,
        )
        self.ctx.on_cleanup(lambda: hotkeys.unregister("day_timer.next_day"))
        self.ctx.on_cleanup(lambda: hotkeys.unregister("day_timer.forward"))
        self.ctx.on_cleanup(lambda: hotkeys.unregister("day_timer.backward"))
        self.ctx.on_cleanup(lambda: hotkeys.unregister("day_timer.calibrate_region"))

    def _create_hud(self, hud: HudApi) -> None:
        widget = _DayTimerHud(
            self.config.day_period_seconds.value,
            self.ctx.tr("hud.waiting"),
        )
        self._hud = widget
        self._progress = widget.segments
        self._label = widget.label
        token = hud.add_widget(self.id, widget, order=0)
        self.ctx.on_cleanup(lambda: hud.remove_widget(token))

    def _on_frame(self, event: FrameCaptured) -> None:
        if self._calibrating or not self.config.auto_detect.value or self._detector is None:
            return
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        if region is None:
            return
        language = self.config.language.value
        result = self._detector.detect(
            event.image,
            region,
            language,
            self.config.score_threshold.value / 100,
            hdr=self.config.hdr_processing.value,
        )
        if result is None:
            return
        self.ctx.log.debug(
            "detect dayx time: %.3fs lang: %s score: %.2f, %.2f, %.2f",
            result.seconds,
            language,
            *result.scores,
        )
        if result.day is not None:
            self._detected_day(result.day)

    def _detected_day(self, day: int) -> None:
        """Legacy restarts the countdown on every hit, so it effectively starts when the DAY banner fades."""
        if (
            day == self.day
            and self.phase == _initial_phase(day)
            and self._phase_started is not None
            and time.monotonic() - self._phase_started < _BANNER_REFRESH_SECONDS
        ):
            self._phase_started = time.monotonic()
            return
        self._start_day(day)
        self.ctx.log.info("Day %d started.", day)

    def _calibrate_region(self) -> None:
        """Suspend template matching while the full-screen selector has the event loop."""
        if self._calibrating:
            return
        self._calibrating = True
        try:
            self.ctx.services.require(RegionApi).request_region(
                _REGION_KEY, self.ctx.tr("settings.calibrate.annotate")
            )
        finally:
            self._calibrating = False

    def _start_next_day(self, source: str = "shortcut") -> None:
        # Legacy cycles DAY I -> DAY II -> DAY I; DAY III (boss) also wraps to a new expedition.
        day = 2 if self.day == 1 else 1
        self._start_day(day)
        self.ctx.log.info("Day %d started by %s.", day, source)

    def _start_day(self, day: int) -> None:
        self.day = day
        self.phase = _initial_phase(day)
        self._phase_started = time.monotonic()
        self.ctx.publish(DayPhaseChanged(self.day, self.phase))
        self._update_timer()

    def _forward(self, source: str = "shortcut") -> None:
        self._shift(-self.config.forward_seconds.value, "forwarded", source)

    def _backward(self, source: str = "shortcut") -> None:
        self._shift(self.config.backward_seconds.value, "rewound", source)

    def _shift(self, seconds: int, action: str, source: str) -> None:
        if self._phase_started is None:
            self.ctx.log.info("Day timer not started; ignored %s request by %s.", action, source)
            return
        self._phase_started += seconds
        self.ctx.log.info("Day timer %s %ds by %s.", action, abs(seconds), source)
        self._update_timer()

    def _advance_phases(self, now: float) -> None:
        """Legacy phase walk: move forward when a phase expires and back when its start is in the future."""
        assert self.day is not None and self.phase is not None and self._phase_started is not None
        if self.day == 3:
            # DAY III only counts the boss fight up; it has no circle phases to step back into.
            self._phase_started = min(self._phase_started, now)
            return
        periods = self.config.day_period_seconds.value
        while self.phase != Phase.NIGHT_BOSS and now - self._phase_started > periods[int(self.phase)]:
            self._phase_started += periods[int(self.phase)]
            self.phase = Phase(int(self.phase) + 1)
            self.ctx.log.info("Phase progress to %s.", self.phase.name)
            self.ctx.publish(DayPhaseChanged(self.day, self.phase))
        while now < self._phase_started:
            if self.phase == Phase.FIRST_CIRCLE_STABLE:
                self._phase_started = now
                break
            self.phase = Phase(int(self.phase) - 1)
            self._phase_started -= periods[int(self.phase)]
            self.ctx.log.info("Phase back to %s.", self.phase.name)
            self.ctx.publish(DayPhaseChanged(self.day, self.phase))

    def _update_timer(self) -> None:
        if self.day is None or self.phase is None or self._phase_started is None:
            return
        now = time.monotonic()
        self._advance_phases(now)
        elapsed = now - self._phase_started
        day = "I" * self.day
        if self.day == 3:
            text = self.ctx.tr("hud.day3", day=day, elapsed=format_period(int(elapsed)))
            progress = 400
        elif self.phase == Phase.NIGHT_BOSS:
            text = self.ctx.tr("hud.boss", day=day, elapsed=format_period(int(elapsed)))
            progress = 400
        else:
            index = int(self.phase)
            duration = self.config.day_period_seconds.value[index]
            text = self.ctx.tr(
                "hud.phase",
                day=day,
                remaining=format_period(int(duration - elapsed)),
                circle=self.ctx.tr("hud.circle.first" if index < 2 else "hud.circle.second"),
                action=self.ctx.tr("hud.action.start" if index % 2 == 0 else "hud.action.end"),
            )
            progress = int((index + elapsed / duration) * 100)
        if self._label is not None:
            self._label.setText(text)
        for index, segment in enumerate(self._progress):
            value = min(1.0, max(0.0, progress / 100 - index))
            segment.setValue(round(value * segment.maximum()))

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        panel = SettingsPanel(parent)
        hotkeys = self.ctx.services.require(HotkeyApi)
        basic = SettingSection(self.ctx.tr("settings.basic.title"))
        basic.addCards(
            ConfigSwitchCard(
                self.config.auto_detect,
                FluentIcon.CAMERA,
                self.ctx.tr("settings.auto.title"),
                self.ctx.tr("settings.auto.content"),
            ),
            ConfigChoiceCard(
                self.config.language,
                [(key, self.ctx.tr(f"settings.language.{key}")) for key in ("chs", "cht", "eng", "jp")],
                FluentIcon.LANGUAGE,
                self.ctx.tr("settings.language.title"),
            ),
            HotkeySettingCard(
                hotkeys,
                hotkeys.binding("day_timer.calibrate_region", HotkeyBinding(None)),
                lambda binding: hotkeys.set_binding("day_timer.calibrate_region", binding),
                FluentIcon.SYNC,
                self.ctx.tr("settings.calibrate.title"),
                self.ctx.tr("settings.calibrate.content"),
                actions=[(self.ctx.tr("settings.calibrate.button"), self._calibrate_region)],
            ),
            MultiButtonSettingCard(
                [
                    (self.ctx.tr("settings.manual.next_day"), lambda: self._start_next_day("button")),
                    (self.ctx.tr("settings.manual.backward"), lambda: self._backward("button")),
                    (self.ctx.tr("settings.manual.forward"), lambda: self._forward("button")),
                ],
                FluentIcon.STOP_WATCH,
                self.ctx.tr("settings.manual.title"),
                self.ctx.tr("settings.manual.content"),
            ),
        )
        shortcuts = SettingSection(self.ctx.tr("settings.shortcuts.title"))
        shortcuts.addCards(
            HotkeySettingCard(
                hotkeys,
                hotkeys.binding(
                    "day_timer.next_day",
                    HotkeyBinding(InputDevice.KEYBOARD, ("ctrl", "shift", "d")),
                ),
                lambda binding: hotkeys.set_binding("day_timer.next_day", binding),
                FluentIcon.SYNC,
                self.ctx.tr("settings.shortcuts.next_day.title"),
                self.ctx.tr("settings.shortcuts.next_day.content"),
            ),
            HotkeySettingCard(
                hotkeys,
                hotkeys.binding(
                    "day_timer.forward",
                    HotkeyBinding(InputDevice.KEYBOARD, ("ctrl", "shift", "right")),
                ),
                lambda binding: hotkeys.set_binding("day_timer.forward", binding),
                FluentIcon.SYNC,
                self.ctx.tr("settings.shortcuts.forward.title"),
                self.ctx.tr("settings.shortcuts.forward.content"),
            ),
            HotkeySettingCard(
                hotkeys,
                hotkeys.binding(
                    "day_timer.backward",
                    HotkeyBinding(InputDevice.KEYBOARD, ("ctrl", "shift", "left")),
                ),
                lambda binding: hotkeys.set_binding("day_timer.backward", binding),
                FluentIcon.SYNC,
                self.ctx.tr("settings.shortcuts.backward.title"),
                self.ctx.tr("settings.shortcuts.backward.content"),
            ),
        )
        advanced = SettingSection(self.ctx.tr("settings.advanced.title"))
        advanced.addCards(
            ConfigRangeCard(
                self.config.forward_seconds, FluentIcon.SYNC, self.ctx.tr("settings.forward.title")
            ),
            ConfigRangeCard(
                self.config.backward_seconds, FluentIcon.SYNC, self.ctx.tr("settings.backward.title")
            ),
            ConfigRangeCard(
                self.config.score_threshold,
                FluentIcon.DEVELOPER_TOOLS,
                self.ctx.tr("settings.threshold.title"),
                formatter=lambda value: f"{value}%",
            ),
            ConfigSwitchCard(
                self.config.hdr_processing,
                FluentIcon.BRIGHTNESS,
                self.ctx.tr("settings.hdr.title"),
                self.ctx.tr("settings.hdr.content"),
            ),
        )
        panel.addSection(basic)
        panel.addSection(shortcuts)
        panel.addSection(advanced)
        return panel


def _initial_phase(day: int) -> Phase:
    return Phase.NIGHT_BOSS if day == 3 else Phase.FIRST_CIRCLE_STABLE
