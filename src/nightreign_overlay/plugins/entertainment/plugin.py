"""Detect teammate down states and manage a condition-triggered looping cue."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.audio.api import AudioApi
from nightreign_overlay.plugins.audio.config import LoopAudioConfig
from nightreign_overlay.plugins.capture.api import CaptureApi, FrameCaptured, crop_rgb
from nightreign_overlay.plugins.entertainment.config import EntertainmentConfig
from nightreign_overlay.plugins.entertainment.detector import Teammate, detect_rgb
from nightreign_overlay.plugins.entertainment.state import should_start, should_stop
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.plugins.region.api import RegionApi, RegionStatus
from nightreign_overlay.ui.components import (
    ConfigChoiceCard,
    ConfigRangeCard,
    ConfigSwitchCard,
    HotkeySettingCard,
    SettingSection,
    SettingsPanel,
)
from nightreign_overlay.ui.components.audio_settings import LoopAudioSettingCard

_REGION_KEY = "entertainment.teammates"
_REGION_COLOR = "#a85be8"
_CALIBRATE = "entertainment.calibrate_region"


class EntertainmentPlugin(Plugin):
    manifest = PluginManifest(
        id="entertainment",
        kind=PluginKind.FEATURE,
        icon="GAME",
        order=70,
        requires=("capture", "region", "audio"),
    )
    _completed = pyqtSignal(object, object)

    def on_load(self) -> None:
        self.config = self.ctx.config(EntertainmentConfig)
        self.loop_audio = self.ctx.config(LoopAudioConfig, "audio.down_loop")
        self._executor: ThreadPoolExecutor | None = None
        self._generation = 0
        self._active = False
        self._calibrating = False
        self._pending = False
        self._playing = False
        self._last_states: tuple[str, str] | None = None
        self._candidate_states: tuple[str, str] | None = None
        self._candidate_count = 0
        self._confirmed_result: tuple[Teammate, Teammate] | None = None
        self._stream_acquired = False
        self._completed.connect(self._on_completed, Qt.ConnectionType.QueuedConnection)
        self.config.detect_enabled.valueChanged.connect(self._set_enabled)
        self.loop_audio.enabled.valueChanged.connect(self._loop_audio_enabled_changed)
        self.loop_audio.fade_out.valueChanged.connect(self._update_loop_config)

    def on_activate(self) -> None:
        regions = self.ctx.services.require(RegionApi)
        # Older builds persisted this placeholder as if it were a manual calibration.
        if regions.region(_REGION_KEY) == QRect(0, 0, 320, 160):
            regions.clear_region(_REGION_KEY)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="down-detect")
        self.ctx.on_cleanup(self._stop_worker)
        self.ctx.subscribe(FrameCaptured, self._on_frame)
        hotkeys = self.ctx.services.require(HotkeyApi)
        hotkeys.register(_CALIBRATE, HotkeyBinding(None), self._calibrate)
        self.ctx.on_cleanup(lambda: hotkeys.unregister(_CALIBRATE))
        self._set_enabled(self.config.detect_enabled.value)

    def _set_enabled(self, enabled: bool) -> None:
        if not hasattr(self, "_active"):
            return
        if enabled and not self._active:
            self._active = True
            self._last_states = None
            self._candidate_states = None
            self._candidate_count = 0
            self._confirmed_result = None
            self._generation += 1
            capture = self.ctx.services.get(CaptureApi)
            if capture is not None:
                capture.acquire_stream(self.id)
                self._stream_acquired = True
        elif not enabled and self._active:
            self._active = False
            self._generation += 1
            self._pending = False
            capture = self.ctx.services.get(CaptureApi)
            if capture is not None:
                capture.release_stream(self.id)
            self._stream_acquired = False
            self._stop_loop(immediate=True)

    def _update_loop_config(self, *_args: object) -> None:
        audio = self.ctx.services.get(AudioApi)
        if audio is not None:
            audio.set_loop_fade_out(self.id, self.loop_audio.fade_out.value)

    def _loop_audio_enabled_changed(self, enabled: bool) -> None:
        if not enabled:
            self._stop_loop(immediate=True)
        self._update_loop_config()

    def _on_frame(self, event: FrameCaptured) -> None:
        if not self._active or self._calibrating or self._pending:
            return
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        if region is None:
            self._stop_loop(immediate=True)
            return
        image = crop_rgb(event.image, region)
        if image is None or self._executor is None:
            return
        self._pending = True
        generation = self._generation
        future: Future[tuple[Teammate, Teammate]] = self._executor.submit(detect_rgb, image)

        def done(job: Future[tuple[Teammate, Teammate]]) -> None:
            try:
                result = job.result()
            except Exception:
                self.ctx.log.exception("Teammate down-state detection failed")
                result = None
            self._completed.emit((generation, result), region)

        future.add_done_callback(done)

    def _on_completed(self, payload: tuple[int, tuple[Teammate, Teammate] | None], region: QRect) -> None:
        generation, result = payload
        if generation != self._generation:
            self._pending = False
            return
        self._pending = False
        if not self._active:
            return
        regions = self.ctx.services.get(RegionApi)
        if regions is None or regions.region(_REGION_KEY) != region:
            return
        if result is None:
            self._stop_loop(immediate=True)
            return
        state_signature = tuple(self._state_key(teammate) for teammate in result)
        if state_signature == self._candidate_states:
            self._candidate_count += 1
        else:
            self._candidate_states = state_signature
            self._candidate_count = 1
        if self._candidate_count < self.config.stable_detections.value:
            return

        self._confirmed_result = result
        if state_signature != self._last_states:
            self._last_states = state_signature
            states = (
                ", ".join(
                    f"teammate {index}: {self._describe_state(teammate)}"
                    for index, teammate in enumerate(result, start=1)
                    if teammate.present
                )
                or "no teammates"
            )
            self.ctx.log.info("Teammate status changed: %s", states)
        if not self._playing:
            if should_start(self._confirmed_result, self.config.start_condition.value):
                self._start_loop()
        else:
            if should_stop(self._confirmed_result, self.config.stop_condition.value):
                self._stop_loop()

    @staticmethod
    def _state_key(teammate: Teammate) -> str:
        if not teammate.present:
            return "absent"
        if not teammate.down:
            return "upright"
        if teammate.stages >= 3:
            return "three-down"
        return "down"

    @staticmethod
    def _describe_state(teammate: Teammate) -> str:
        state = EntertainmentPlugin._state_key(teammate)
        return {
            "absent": "absent",
            "upright": "upright",
            "down": "down (one or two stages)",
            "three-down": "three-down",
        }[state]

    def _start_loop(self) -> None:
        if not self.loop_audio.enabled.value or not self.loop_audio.path.value:
            return
        audio = self.ctx.services.get(AudioApi)
        if audio is not None and audio.play_loop(
            self.loop_audio.path.value,
            self.loop_audio.volume.value,
            self.loop_audio.fade_in.value,
            owner=self.id,
        ):
            self._playing = True
            audio.set_loop_fade_out(self.id, self.loop_audio.fade_out.value)
            self.ctx.log.info("Started teammate down-state loop audio")

    def _stop_loop(self, immediate: bool = False) -> None:
        audio = self.ctx.services.get(AudioApi)
        if audio is not None:
            audio.stop_loop(self.id, 0 if immediate else self.loop_audio.fade_out.value)
        if self._playing:
            self.ctx.log.info("Stopped teammate down-state loop audio")
        self._playing = False

    def _stop_worker(self) -> None:
        self._generation += 1
        self._active = False
        self._stop_loop(immediate=True)
        capture = self.ctx.services.get(CaptureApi)
        if capture is not None and self._stream_acquired:
            capture.release_stream(self.id)
            self._stream_acquired = False
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None

    def _calibrate(self) -> None:
        if self._calibrating:
            return
        self._calibrating = True
        self._generation += 1
        self._pending = False
        try:
            self.ctx.services.require(RegionApi).request_region(
                _REGION_KEY, self.ctx.tr("settings.region.annotate"), _REGION_COLOR
            )
        finally:
            self._calibrating = False

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        tr = self.ctx.tr
        panel = SettingsPanel(parent)
        section = SettingSection(tr("settings.group"))
        section.addCards(
            ConfigSwitchCard(
                self.config.detect_enabled,
                FluentIcon.VIEW,
                tr("settings.enabled.title"),
                tr("settings.enabled.content"),
            ),
            HotkeySettingCard(
                self.ctx.services.require(HotkeyApi),
                _CALIBRATE,
                HotkeyBinding(None),
                FluentIcon.SYNC,
                tr("settings.region.title"),
                tr("settings.region.content"),
                actions=[(tr("settings.region.button"), self._calibrate)],
                accessories=[RegionStatus(self.ctx.services, _REGION_KEY, _REGION_COLOR)],
            ),
            ConfigChoiceCard(
                self.config.start_condition,
                [("all_down", tr("settings.all_down")), ("all_three", tr("settings.all_three"))],
                FluentIcon.PLAY,
                tr("settings.start.title"),
            ),
            ConfigChoiceCard(
                self.config.stop_condition,
                [("all_up", tr("settings.all_up")), ("any_up", tr("settings.any_up"))],
                FluentIcon.CLOSE,
                tr("settings.stop.title"),
            ),
        )
        section.addCard(
            LoopAudioSettingCard(
                self.loop_audio,
                self.ctx.services.require(AudioApi),
                self.id,
                tr("audio.loop_title"),
            )
        )
        panel.addSection(section)
        advanced = SettingSection(tr("settings.advanced.title"))
        advanced.addCard(
            ConfigRangeCard(
                self.config.stable_detections,
                FluentIcon.SYNC,
                tr("settings.advanced.stable_detections.title"),
                tr("settings.advanced.stable_detections.content"),
            )
        )
        panel.addSection(advanced)
        return panel

    def on_deactivate(self) -> None:
        self._stop_worker()

    def reset_settings(self) -> None:
        super().reset_settings()
        if (regions := self.ctx.services.get(RegionApi)) is not None:
            regions.clear_region(_REGION_KEY)
