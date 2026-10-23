"""Track the attack buff's 20-second status-meter checks, up to ten stacks."""

from __future__ import annotations

import time

from PyQt6.QtCore import QRect, QTimer
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.audio.api import AudioNotifications
from nightreign_overlay.plugins.capture.api import CaptureApi, FrameCaptured, crop_rgb, hdr_to_sdr
from nightreign_overlay.plugins.debuff_timer.detector import DebuffDetector
from nightreign_overlay.plugins.hud.api import HudApi, HudTimerBar
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.plugins.region.api import RegionApi, RegionStatus
from nightreign_overlay.ui.components import HotkeySettingCard, SettingSection, SettingsPanel
from nightreign_overlay.ui.components.audio_settings import audio_section

_REGION_KEY = "debuff_timer.meter_region"
_CALIBRATE = "debuff_timer.calibrate_region"
_START = "debuff_timer.start"
_END = "debuff_timer.end"
_COLOR = "#B87945"
_PERIOD = 20.0
_MAX_LEVEL = 10


def _fit_meter_region(rect: QRect) -> QRect:
    """Fit the reference aspect inside the selection, anchored at left-center."""
    width, height = rect.width(), rect.height()
    if width * 32 > height * 45:
        width = max(1, round(height * 45 / 32))
    else:
        height = max(1, round(width * 32 / 45))
    return QRect(rect.x(), rect.y() + (rect.height() - height) // 2, width, height)


class DebuffTimerPlugin(Plugin):
    manifest = PluginManifest(
        id="debuff_timer",
        kind=PluginKind.FEATURE,
        icon="IOT",
        requires=("capture", "hud", "input", "region", "audio"),
        default_enabled=False,
        order=25,
    )

    def on_load(self) -> None:
        self._audio = AudioNotifications(self.ctx, ("check",))
        self._active = False
        self._streaming = False
        self._calibrating = False
        self._pending = False
        self._generation = 0
        self._level = 0
        self._deadline: float | None = None
        self._retry_at = 0.0
        self._detector: DebuffDetector | None = None
        self._hud: HudTimerBar | None = None
        self._clock = QTimer(self)
        self._clock.setInterval(100)
        self._clock.timeout.connect(self._tick)

    def on_activate(self) -> None:
        self._detector = DebuffDetector(self.ctx.resource("icons"))
        self._active = True
        hotkeys = self.ctx.services.require(HotkeyApi)
        for action, callback in (
            (_CALIBRATE, self._calibrate_region),
            (_START, self._manual_start),
            (_END, self._manual_end),
        ):
            hotkeys.register(action, HotkeyBinding(None), callback)
            self.ctx.on_cleanup(lambda action=action: hotkeys.unregister(action))
        hud = self.ctx.services.require(HudApi)
        self._hud = HudTimerBar(_COLOR)
        token = hud.add_widget(self.id, self._hud, order=25)
        self.ctx.on_cleanup(lambda: hud.remove_widget(token))
        self.ctx.subscribe(FrameCaptured, self._on_frame)
        self.ctx.on_cleanup(self._stop)
        self._reset_cycle()
        self._clock.start()

    def on_deactivate(self) -> None:
        self._stop()
        self._hud = None
        self._detector = None

    def _set_stream(self, enabled: bool) -> None:
        if enabled == self._streaming:
            return
        capture = self.ctx.services.require(CaptureApi)
        self._streaming = enabled
        if enabled:
            capture.acquire_stream(self.id)
        else:
            capture.release_stream(self.id)

    def _stop(self) -> None:
        self._active = False
        self._clock.stop()
        self._reset_cycle()

    def _reset_cycle(self, *, stop_audio: bool = True) -> None:
        if stop_audio:
            self._audio.reset()
        else:
            # The boundary notification must finish even when this check clears
            # the buff. Manual stop/deactivation still stops owned playback.
            self._audio.timeline.reset()
        self._generation += 1
        self._pending = False
        self._retry_at = 0.0
        self._level = 0
        self._deadline = None
        self._set_stream(self._active)
        self._update_hud()

    def _detect(self, frame: FrameCaptured, region: QRect) -> bool | None:
        if self._detector is None:
            return None
        # A partially clipped region cannot establish that the meter is absent.
        if not frame.image.rect().translated(frame.image.offset()).contains(region):
            return None
        rgb = crop_rgb(frame.image, region)
        if rgb is None or min(rgb.shape[:2]) < 32:
            return None
        if frame.hdr:
            rgb = hdr_to_sdr(rgb)
        return self._detector.detect(rgb).present

    def _on_frame(self, frame: FrameCaptured) -> None:
        # Other plugins' frames must never change a running countdown.
        if not self._active or not self._streaming or self._calibrating or self._deadline is not None:
            return
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        if region is not None and self._detect(frame, region):
            self._start_cycle()

    def _start_cycle(self) -> None:
        self._audio.reset()
        self._generation += 1
        self._pending = False
        self._retry_at = 0.0
        self._level = 1
        self._deadline = time.monotonic() + _PERIOD
        self._set_stream(False)
        self._update_audio(time.monotonic())
        self.ctx.log.info("Status meter attack buff started: Lv.1; next check in 20s")
        self._update_hud()

    def _manual_start(self) -> None:
        if self._active and not self._calibrating:
            self._start_cycle()

    def _manual_end(self) -> None:
        if self._active:
            self.ctx.log.info("Status meter attack buff manually cleared from Lv.%s", self._level)
            self._reset_cycle()

    def _tick(self) -> None:
        if not self._active or self._calibrating:
            return
        now = time.monotonic()
        self._update_audio(now)
        if self._deadline is not None and now >= max(self._deadline, self._retry_at) and not self._pending:
            region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
            if region is not None:
                self._pending = True
                generation = self._generation
                self.ctx.services.require(CaptureApi).request_frame(
                    lambda frame: self._on_check(frame, region, generation)
                )
        self._update_hud()

    def _update_audio(self, now: float) -> None:
        if self._deadline is not None:
            self._audio.update(
                _PERIOD - (self._deadline - now),
                {"check": _PERIOD - self._audio.cues["check"].seconds.value},
            )

    def _on_check(self, frame: FrameCaptured | None, region: QRect, generation: int) -> None:
        if not self._active or generation != self._generation:
            return
        self._pending = False
        if self._calibrating:
            return
        regions = self.ctx.services.require(RegionApi)
        present = (
            self._detect(frame, region)
            if frame is not None and regions.region(_REGION_KEY) == region
            else None
        )
        if present is None:
            # Capture/region failure is not a visual negative. Retry without
            # creating a second outstanding request or changing the stack.
            self._retry_at = time.monotonic() + 1.0
            self.ctx.log.warning("Status meter check unavailable; retrying in 1s")
            return
        if present:
            self._level = min(_MAX_LEVEL, self._level + 1)
            self._deadline = time.monotonic() + _PERIOD
            self._audio.timeline.reset()
            self._update_audio(time.monotonic())
            self._retry_at = 0.0
            self.ctx.log.info("Status meter present: attack buff Lv.%s; next check in 20s", self._level)
        else:
            self.ctx.log.info("Status meter absent: attack buff cleared from Lv.%s", self._level)
            self._reset_cycle(stop_audio=False)
        self._update_hud()

    def _update_hud(self) -> None:
        if self._hud is None:
            return
        if self._deadline is None:
            self._hud.set_progress(0, "")
            return
        remaining = max(0.0, self._deadline - time.monotonic())
        text = self.ctx.tr("hud.text", level=self._level, remaining=f"{remaining:.1f}")
        self._hud.set_progress(remaining / _PERIOD, text)

    def _calibrate_region(self) -> None:
        if self._calibrating:
            return
        self._calibrating = True
        self._generation += 1
        self._pending = False
        try:
            regions = self.ctx.services.require(RegionApi)
            selected = regions.request_region(_REGION_KEY, self.ctx.tr("settings.region.annotate"), _COLOR)
            if selected is not None and selected.isValid():
                adjusted = _fit_meter_region(selected)
                regions.save_region(_REGION_KEY, adjusted)
                self.ctx.log.info(
                    "Status meter region fitted to 45:32 at left-center: %s -> %s",
                    selected.getRect(),
                    adjusted.getRect(),
                )
        finally:
            self._calibrating = False

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        tr = self.ctx.tr
        panel = SettingsPanel(parent)
        basic = SettingSection(tr("settings.basic"))
        basic.addCard(
            HotkeySettingCard(
                self.ctx.services.require(HotkeyApi),
                _CALIBRATE,
                HotkeyBinding(None),
                FluentIcon.SYNC,
                tr("settings.region.title"),
                tr("settings.region.content"),
                actions=[(tr("settings.region.button"), self._calibrate_region)],
                accessories=[RegionStatus(self.ctx.services, _REGION_KEY, _COLOR)],
            )
        )
        for action, title, icon in (
            (_START, "settings.start", FluentIcon.PLAY),
            (_END, "settings.end", FluentIcon.PAUSE),
        ):
            basic.addCard(
                HotkeySettingCard(
                    self.ctx.services.require(HotkeyApi), action, HotkeyBinding(None), icon, tr(title)
                )
            )
        panel.addSection(basic)
        panel.addSection(audio_section(self._audio, ("check",)))
        return panel

    def reset_settings(self) -> None:
        self._reset_cycle()
        super().reset_settings()
        hotkeys = self.ctx.services.require(HotkeyApi)
        for action in (_CALIBRATE, _START, _END):
            hotkeys.set_binding(action, HotkeyBinding(None))
        if (regions := self.ctx.services.get(RegionApi)) is not None:
            regions.clear_region(_REGION_KEY)
