"""Character art (ultimate) countdown: detect the art icon shortly after the art key is pressed."""

from __future__ import annotations

import time
from dataclasses import dataclass

from PyQt6.QtCore import QRect, QTimer
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.core.debug import DebugImageApi
from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.art_timer.config import ArtTimerConfig
from nightreign_overlay.plugins.art_timer.detector import ArtDetector
from nightreign_overlay.plugins.art_timer.undertaker_detector import pink_ratio
from nightreign_overlay.plugins.audio.api import AudioApi, AudioNotifications
from nightreign_overlay.plugins.audio.config import LoopAudioConfig
from nightreign_overlay.plugins.audio.defaults import bundled_loop_path
from nightreign_overlay.plugins.capture.api import CaptureApi, FrameCaptured, crop_rgb, hdr_to_sdr
from nightreign_overlay.plugins.hud.api import HudApi, HudTimerBar
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.plugins.region.api import RegionApi, RegionStatus
from nightreign_overlay.ui.components import (
    ConfigDoubleSpinCard,
    ConfigRangeCard,
    ConfigSwitchCard,
    HotkeySettingCard,
    SettingSection,
    SettingsPanel,
)
from nightreign_overlay.ui.components.audio_settings import audio_section

_REGION_KEY = "art_timer.art_region"
_USE_ART = "art_timer.use_art"
_CALIBRATE_REGION = "art_timer.calibrate_region"
# The legacy app shipped both shortcuts unbound.
_HOTKEYS = (_USE_ART, _CALIBRATE_REGION)
# Legacy colour of the selector annotation.
_REGION_COLOR = "#3235eb"


@dataclass(frozen=True)
class _ArtInfo:
    """Legacy ``art_info``: the effect starts ``delay`` seconds after detection and lasts ``duration``."""

    delay: float
    duration: float
    color: str


_ART_INFO = {
    "duchess": _ArtInfo(2, 13, "#cccccc"),
    "recluse": _ArtInfo(2, 13, "#d11010"),
    "revenant": _ArtInfo(2, 13, "#9bdfdf"),
    "scholar": _ArtInfo(2, 20, "#cecece"),
    "executor": _ArtInfo(2, 15, "#c98941"),
}
_ART_ROLES = tuple(_ART_INFO)


def _format_period(seconds: int) -> str:
    return f"{max(seconds, 0) // 60}:{max(seconds, 0) % 60:02d}"


class ArtTimerPlugin(Plugin):
    manifest = PluginManifest(
        id="art_timer",
        kind=PluginKind.FEATURE,
        icon="CALORIES",
        requires=("capture", "hud", "input", "region", "audio"),
        order=20,
    )

    def on_load(self) -> None:
        self.config = self.ctx.config(ArtTimerConfig)
        self._audio = AudioNotifications(self.ctx, ("start", "end", "undertaker"))
        self._loop_audio = {
            role: self.ctx.config(LoopAudioConfig, f"audio.{role}_loop") for role in _ART_ROLES
        }
        executor_loop = self._loop_audio["executor"]
        if (
            not executor_loop.path.value
            and executor_loop.volume.value == 100
            and executor_loop.fade_in.value == 0
            and executor_loop.fade_out.value == 0
        ):
            executor_loop.volume.set(10)
            executor_loop.fade_out.set(1.0)
        self._loop_owner: str | None = None
        self._art_type: str | None = None
        self._art_started: float | None = None
        self._detector: ArtDetector | None = None
        self._hud: HudTimerBar | None = None
        self._undertaker_started: float | None = None
        self._undertaker_audio_started: float | None = None
        self._undertaker_active = False
        self._undertaker_stream = False
        self.config.undertaker_enabled.valueChanged.connect(self._set_undertaker_enabled)
        self._calibrating = False
        self._detect_generation = 0
        self._clock = QTimer(self)
        self._clock.setInterval(100)
        self._clock.timeout.connect(self._update_timer)
        # Pressing the art key again before the detection restarts the delay, like the legacy app.
        self._detect_timer = QTimer(self)
        self._detect_timer.setSingleShot(True)
        self._detect_timer.timeout.connect(self._detect_art)
        for role, config in self._loop_audio.items():
            config.enabled.valueChanged.connect(
                lambda enabled, role=role: self._stop_role_loop(role, immediate=True) if not enabled else None
            )
            config.fade_out.valueChanged.connect(
                lambda seconds, role=role: self._update_loop_fade(role, seconds)
            )

    def on_activate(self) -> None:
        self._detector = ArtDetector(self.ctx.resource("icons"))
        if missing := self._detector.missing():
            self.ctx.log.error("Art icons are unavailable: %s", ", ".join(missing))
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        self.ctx.log.info("Art region: %s", list(region.getRect()) if region else None)
        self._register_hotkeys(self.ctx.services.require(HotkeyApi))
        self._create_hud(self.ctx.services.require(HudApi))
        self.ctx.subscribe(FrameCaptured, self._on_undertaker_frame)
        self.ctx.on_cleanup(lambda: self._set_undertaker_enabled(False))
        self._set_undertaker_enabled(self.config.undertaker_enabled.value)
        self._clock.start()
        self.ctx.on_cleanup(self._clock.stop)
        self.ctx.on_cleanup(self._detect_timer.stop)

    def on_deactivate(self) -> None:
        self._set_undertaker_enabled(False)
        self._stop_loop(immediate=True)
        self._audio.reset()
        self._art_type = self._art_started = None
        self._detect_generation += 1
        self._hud = None
        self._detector = None

    def _register_hotkeys(self, hotkeys: HotkeyApi) -> None:
        callbacks = {_USE_ART: self._use_art, _CALIBRATE_REGION: self._calibrate_region}
        for action in _HOTKEYS:
            hotkeys.register(action, HotkeyBinding(None), callbacks[action])
            self.ctx.on_cleanup(lambda action=action: hotkeys.unregister(action))

    def _create_hud(self, hud: HudApi) -> None:
        widget = HudTimerBar(_ART_INFO["duchess"].color)
        self._hud = widget
        token = hud.add_widget(self.id, widget, order=20)
        self.ctx.on_cleanup(lambda: hud.remove_widget(token))
        # The HUD shows every new widget; an idle countdown hides itself again.
        self._update_timer()

    def _set_undertaker_enabled(self, enabled: bool) -> None:
        capture = self.ctx.services.get(CaptureApi)
        if enabled and self._detector is not None and not self._undertaker_stream:
            if capture is not None:
                capture.acquire_stream(self.id)
                self._undertaker_stream = True
        elif not enabled:
            if self._undertaker_stream and capture is not None:
                capture.release_stream(self.id)
            self._undertaker_stream = False
            self._cancel_undertaker()

    def _cancel_undertaker(self) -> None:
        self._undertaker_active = False
        self._undertaker_started = None
        self._undertaker_audio_started = None
        self._update_timer()

    def _on_undertaker_frame(self, frame: FrameCaptured) -> None:
        if not self._undertaker_stream or self._calibrating:
            return
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        image = crop_rgb(frame.image, region) if region is not None else None
        if image is None:
            return
        if frame.hdr:
            image = hdr_to_sdr(image)
        active = pink_ratio(image) >= self.config.undertaker_pink_percent.value / 100
        if active and not self._undertaker_active and self._undertaker_started is None:
            self._undertaker_started = time.monotonic()
            self._undertaker_audio_started = self._undertaker_started
            self.ctx.log.info("Undertaker extra art activated")
        # Inactive rearms edge detection but never cancels a running countdown.
        self._undertaker_active = active
        self._update_timer()

    def _update_undertaker_timer(self) -> bool:
        if self._hud is None or self._undertaker_started is None:
            return False
        duration = self.config.undertaker_duration.value
        elapsed = max(0.0, time.monotonic() - self._undertaker_started)
        if elapsed >= duration:
            self._undertaker_started = None
            return False
        text = self.ctx.tr(
            "hud.text",
            name=self.ctx.tr("hud.undertaker"),
            remaining=_format_period(int(max(duration - elapsed, 0))),
        )
        self._hud.set_progress(1 - elapsed / duration, text, "#c28aba")
        return True

    # -- detection ----------------------------------------------------------------------------

    def _use_art(self) -> None:
        self._detect_generation += 1
        delay = self.config.detect_delay_ms.value
        self.ctx.log.info("Will detect art in %s seconds.", delay / 1000)
        self._detect_timer.start(delay)

    def _detect_art(self) -> None:
        """Request a frame for the shortcut-triggered template matcher."""
        if self._calibrating or self._detector is None:
            return
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        if region is not None:
            generation = self._detect_generation
            self.ctx.services.require(CaptureApi).request_frame(
                lambda frame, region=region: self._on_art_frame(frame, region, generation)
            )

    def _on_art_frame(self, frame: FrameCaptured | None, region: QRect, generation: int) -> None:
        if generation != self._detect_generation or self._calibrating or self._detector is None:
            return
        regions = self.ctx.services.get(RegionApi)
        if regions is None or regions.region(_REGION_KEY) != region:
            return
        result = (
            self._detector.detect(
                frame.image, region, self.config.match_threshold.value / 1000, hdr=frame.hdr
            )
            if frame is not None
            else None
        )
        if result is not None:
            debug_image = crop_rgb(frame.image, region) if frame is not None else None
            debug = self.ctx.services.get(DebugImageApi)
            if debug_image is not None and debug is not None:
                debug.save(
                    "art_timer_ultimate",
                    debug_image,
                    {
                        "art_type": result.art_type,
                        "best_score": result.best_score,
                        "scores": result.scores,
                        "region": region,
                    },
                    cooldown_seconds=600,
                )
            for art_type, score in result.scores.items():
                self.ctx.log.info("Art type: %s, score: %.4f", art_type, score)
            if result.art_type is not None:
                self.ctx.log.info("Detected art type: %s, score: %.4f", result.art_type, result.best_score)
            else:
                self.ctx.log.info("No art detected, best score: %.4f", result.best_score)
        if result is None or result.art_type is None:
            self.ctx.log.info("No art detected.")
            return
        self.ctx.log.info("detected art: %s", result.art_type)
        self._stop_loop(immediate=True)
        self._audio.reset()
        self._art_type = result.art_type
        self._art_started = time.monotonic()
        # Start the role loop as soon as the detected art countdown appears.
        # The HUD countdown includes the activation delay, so audio should cover
        # that full visible countdown instead of waiting for effect time to begin.
        self._start_role_loop(self._art_type)
        self._update_timer()

    # -- countdown ----------------------------------------------------------------------------

    def _update_timer(self) -> None:
        if self._undertaker_audio_started is not None:
            cue = self._audio.cues["undertaker"]
            if time.monotonic() - self._undertaker_audio_started >= cue.seconds.value:
                self._undertaker_audio_started = None
                self._audio.play(cue)
        if self._art_type is not None and self._art_started is not None:
            info = _ART_INFO[self._art_type]
            elapsed = time.monotonic() - self._art_started
            self._audio.update(
                elapsed,
                {
                    "start": info.delay + self._audio.cues["start"].seconds.value,
                    "end": info.delay + info.duration - self._audio.cues["end"].seconds.value,
                },
            )
            if elapsed <= info.delay + info.duration:
                self._start_role_loop(self._art_type)
            else:
                # Audio lifetime follows its own countdown even while the
                # shared HUD is displaying Undertaker's extra art.
                self._stop_loop()
                self._art_type = self._art_started = None
        if self._update_undertaker_timer():
            return
        if self._hud is None:
            return
        if self._art_type is None or self._art_started is None:
            self._hud.set_progress(0.0, "")
            return
        info = _ART_INFO[self._art_type]
        elapsed = max(0.0, time.monotonic() - self._art_started - info.delay)
        if elapsed > info.duration:
            self._stop_loop()
            self._art_type = self._art_started = None
            self._hud.set_progress(0.0, "")
            return
        text = self.ctx.tr(
            "hud.text",
            name=self.ctx.tr(f"hud.{self._art_type}"),
            remaining=_format_period(int(max(info.duration - elapsed, 0))),
        )
        self._hud.set_progress(1.0 - elapsed / info.duration, text, info.color)

    def _loop_owner_for(self, role: str) -> str:
        return f"{self.id}:art:{role}"

    def _start_role_loop(self, role: str) -> None:
        config = self._loop_audio[role]
        path = config.path.value or (str(bundled_loop_path(self.id, role)) if role == "executor" else "")
        if self._loop_owner is not None or not config.enabled.value or not path:
            return
        audio = self.ctx.services.get(AudioApi)
        owner = self._loop_owner_for(role)
        if audio is not None and audio.play_loop(
            path, config.volume.value, config.fade_in.value, owner=owner
        ):
            self._loop_owner = owner
            audio.set_loop_fade_out(owner, config.fade_out.value)
            self.ctx.log.info("Started %s art loop audio", role)

    def _stop_role_loop(self, role: str, *, immediate: bool = False) -> None:
        if self._loop_owner == self._loop_owner_for(role):
            self._stop_loop(immediate=immediate)

    def _stop_loop(self, *, immediate: bool = False) -> None:
        if self._loop_owner is None:
            return
        owner = self._loop_owner
        config = next(
            (item for role, item in self._loop_audio.items() if self._loop_owner_for(role) == owner), None
        )
        audio = self.ctx.services.get(AudioApi)
        if audio is not None:
            audio.stop_loop(owner, 0 if immediate or config is None else config.fade_out.value)
        self.ctx.log.info("Stopped art loop audio%s", " immediately" if immediate else " with fade-out")
        # Keep the owner while its fade-out is in progress so shutdown or a new
        # recognition can still cancel/remove that stack entry immediately.
        if immediate:
            self._loop_owner = None

    def _update_loop_fade(self, role: str, seconds: float) -> None:
        if self._loop_owner == self._loop_owner_for(role):
            audio = self.ctx.services.get(AudioApi)
            if audio is not None:
                audio.set_loop_fade_out(self._loop_owner, seconds)

    # -- calibration --------------------------------------------------------------------------

    def _calibrate_region(self) -> None:
        if self._calibrating:
            return
        self._calibrating = True
        self._detect_generation += 1
        try:
            self.ctx.services.require(RegionApi).request_region(
                _REGION_KEY, self.ctx.tr("settings.region.annotate"), _REGION_COLOR
            )
        finally:
            self._calibrating = False

    # -- settings -----------------------------------------------------------------------------

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        tr = self.ctx.tr
        panel = SettingsPanel(parent)
        hotkeys = self.ctx.services.require(HotkeyApi)
        basic = SettingSection(tr("settings.basic.title"))
        basic.addCards(
            ConfigSwitchCard(
                self.config.undertaker_enabled, FluentIcon.VIEW, tr("settings.undertaker_enabled.title")
            ),
            HotkeySettingCard(
                hotkeys,
                _CALIBRATE_REGION,
                HotkeyBinding(None),
                FluentIcon.SYNC,
                tr("settings.region.title"),
                tr("settings.region.content"),
                actions=[(tr("settings.region.button"), self._calibrate_region)],
                accessories=[RegionStatus(self.ctx.services, _REGION_KEY, _REGION_COLOR)],
            ),
            HotkeySettingCard(
                hotkeys,
                _USE_ART,
                HotkeyBinding(None),
                FluentIcon.CALORIES,
                tr("settings.use_art.title"),
                tr("settings.use_art.content"),
            ),
        )
        advanced = SettingSection(tr("settings.advanced.title"))
        advanced.addCards(
            ConfigRangeCard(
                self.config.undertaker_pink_percent,
                FluentIcon.PALETTE,
                tr("settings.undertaker_threshold.title"),
                formatter=lambda value: f"{value}%",
            ),
            ConfigDoubleSpinCard(
                self.config.undertaker_duration,
                FluentIcon.HISTORY,
                tr("settings.undertaker_duration.title"),
                formatter=lambda value: f"{value} s",
            ),
            ConfigRangeCard(
                self.config.detect_delay_ms,
                FluentIcon.HISTORY,
                tr("settings.delay.title"),
                tr("settings.delay.content"),
                formatter=lambda value: f"{value} ms",
            ),
            ConfigRangeCard(
                self.config.match_threshold,
                FluentIcon.DEVELOPER_TOOLS,
                tr("settings.threshold.title"),
                tr("settings.threshold.content"),
                formatter=lambda value: f"{value / 1000:.3f}",
            ),
        )
        panel.addSection(basic)
        panel.addSection(advanced)
        audio = self.ctx.services.require(AudioApi)
        loop_cues = tuple(
            (
                self._loop_audio[role],
                audio,
                self._loop_owner_for(role),
                tr(f"roles.{role}"),
                tr(f"roles.{role}"),
                str(bundled_loop_path(self.id, role)) if role == "executor" else "",
            )
            for role in _ART_ROLES
        )
        panel.addSection(audio_section(self._audio, ("end",), loop_cues))
        return panel

    def reset_settings(self) -> None:
        self._cancel_undertaker()
        self._detect_timer.stop()
        self._detect_generation += 1
        self._art_type = self._art_started = None
        self._stop_loop(immediate=True)
        self._audio.reset()
        self._update_timer()
        super().reset_settings()
        executor_loop = self._loop_audio["executor"]
        executor_loop.volume.set(10)
        executor_loop.fade_in.set(0.0)
        executor_loop.fade_out.set(1.0)
        hotkeys = self.ctx.services.require(HotkeyApi)
        for action in _HOTKEYS:
            hotkeys.set_binding(action, HotkeyBinding(None))
        if (regions := self.ctx.services.get(RegionApi)) is not None:
            regions.clear_region(_REGION_KEY)
        self.ctx.log.info("Settings reset to defaults.")
