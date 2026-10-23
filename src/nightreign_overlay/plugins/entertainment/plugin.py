"""Detect teammate down states and manage a condition-triggered looping cue."""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.audio.api import AudioApi
from nightreign_overlay.plugins.audio.config import LoopAudioConfig
from nightreign_overlay.plugins.audio.defaults import bundled_loop_path
from nightreign_overlay.plugins.capture.api import CaptureApi, FrameCaptured, crop_rgb
from nightreign_overlay.plugins.entertainment.config import EntertainmentConfig
from nightreign_overlay.plugins.entertainment.detector import Teammate, detect_rgb
from nightreign_overlay.plugins.entertainment.self_detector import is_down
from nightreign_overlay.plugins.entertainment.state import should_start, should_stop
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.plugins.p2p_latency.api import P2PStateChanged, PeerSnapshot
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
_SELF_REGION_KEY = "entertainment.self_down"
_SELF_CALIBRATE = "entertainment.calibrate_self_region"
_REGION_COLOR = "#a85be8"
_CALIBRATE = "entertainment.calibrate_region"
_ROSTER_MAX_AGE = 5.0


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
        if (
            not self.loop_audio.path.value
            and self.loop_audio.volume.value == 100
            and self.loop_audio.fade_in.value == 0
            and self.loop_audio.fade_out.value == 0
        ):
            self.loop_audio.volume.set(10)
            self.loop_audio.fade_in.set(2.0)
            self.loop_audio.fade_out.set(2.0)
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
        self._self_down: bool | None = None
        self._self_candidate: bool | None = None
        self._self_count = 0
        self._stream_acquired = False
        self._single_peer_at: float | None = None
        self._detect_limit = 2
        self.config.self_down_stop.valueChanged.connect(self._self_enabled_changed)
        self.config.three_player_only.valueChanged.connect(lambda _: self._apply_playback())
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
        self.ctx.subscribe(PeerSnapshot, self._on_peer_snapshot)
        self.ctx.subscribe(P2PStateChanged, self._on_p2p_status)
        hotkeys = self.ctx.services.require(HotkeyApi)
        hotkeys.register(_CALIBRATE, HotkeyBinding(None), self._calibrate)
        self.ctx.on_cleanup(lambda: hotkeys.unregister(_CALIBRATE))
        hotkeys.register(_SELF_CALIBRATE, HotkeyBinding(None), self._calibrate_self)
        self.ctx.on_cleanup(lambda: hotkeys.unregister(_SELF_CALIBRATE))
        self._set_enabled(self.config.detect_enabled.value)

    def _set_enabled(self, enabled: bool) -> None:
        if not hasattr(self, "_active"):
            return
        if enabled and not self._active:
            self._active = True
            self._self_down = self._self_candidate = None
            self._self_count = 0
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
        teammate_count = self._teammate_limit()
        if teammate_count != self._detect_limit:
            self._detect_limit = teammate_count
            self._candidate_states = None
            self._candidate_count = 0
        generation = self._generation
        self_region = (
            self.ctx.services.require(RegionApi).region(_SELF_REGION_KEY)
            if self.config.self_down_stop.value
            else None
        )
        self_image = crop_rgb(event.image, self_region) if self_region is not None else None

        def detect():
            teammates = detect_rgb(image, teammate_count=1) if teammate_count == 1 else detect_rgb(image)
            return teammates, is_down(self_image) if self_image is not None else None

        future = self._executor.submit(detect)

        def done(job: Future) -> None:
            try:
                result, self_result = job.result()
            except Exception:
                self.ctx.log.exception("Down-state detection failed")
                result, self_result = None, None
            self._completed.emit((generation, result, self_result, self_region, teammate_count), region)

        future.add_done_callback(done)

    def _on_completed(self, payload: tuple, region: QRect) -> None:
        generation, result = payload[:2]
        if generation != self._generation:
            self._pending = False
            return
        self._pending = False
        if not self._active:
            return
        if len(payload) >= 5 and payload[4] != self._teammate_limit():
            return
        regions = self.ctx.services.get(RegionApi)
        if regions is None or regions.region(_REGION_KEY) != region:
            return
        if result is None:
            self._stop_loop(immediate=True)
            return
        if len(payload) >= 4 and self.config.self_down_stop.value:
            self_result, self_region = payload[2:4]
            if self_region == regions.region(_SELF_REGION_KEY) and self_result is not None:
                self._confirm_self(self_result)
        state_signature = tuple(self._state_key(teammate) for teammate in result)
        if state_signature == self._candidate_states:
            self._candidate_count += 1
        else:
            self._candidate_states = state_signature
            self._candidate_count = 1
        if self._candidate_count < self.config.stable_detections.value:
            self._apply_playback()
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
        self._apply_playback()

    def _on_peer_snapshot(self, event: PeerSnapshot) -> None:
        # Snapshots are emitted only after a complete successful polling cycle.
        # Connecting peers are not reliable evidence of a one-teammate party.
        self._single_peer_at = (
            time.monotonic() if len(event.peers) == 1 and event.peers[0].state == "connected" else None
        )

    def _on_p2p_status(self, event: P2PStateChanged) -> None:
        if event.status.state != "steam_ready":
            self._single_peer_at = None

    def _teammate_limit(self) -> int:
        if self._single_peer_at is not None and time.monotonic() - self._single_peer_at <= _ROSTER_MAX_AGE:
            return 1
        return 2

    def _self_enabled_changed(self, enabled: bool) -> None:
        self._generation += 1
        self._self_down = self._self_candidate = None
        self._self_count = 0
        if not enabled:
            self._apply_playback()

    def _confirm_self(self, down: bool) -> None:
        if down == self._self_candidate:
            self._self_count += 1
        else:
            self._self_candidate, self._self_count = down, 1
        if self._self_count >= self.config.stable_detections.value and down != self._self_down:
            self._self_down = down
            self.ctx.log.info("Self status changed: %s", "down" if down else "upright")

    def _apply_playback(self) -> None:
        if not self._active:
            return
        if self.config.self_down_stop.value and self._self_down:
            if self._playing:
                self._stop_loop(immediate=True)
            return
        if self._confirmed_result is None:
            return
        if self.config.three_player_only.value and sum(m.present for m in self._confirmed_result) != 2:
            if self._playing:
                self._stop_loop()
            return
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
        path = self.loop_audio.path.value or str(bundled_loop_path(self.id, "down"))
        if not self.loop_audio.enabled.value:
            return
        audio = self.ctx.services.get(AudioApi)
        if audio is not None and audio.play_loop(
            path,
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
        self._single_peer_at = None
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
        self._calibrate_region(_REGION_KEY, "settings.region.annotate")

    def _calibrate_self(self) -> None:
        self._calibrate_region(_SELF_REGION_KEY, "settings.self_region.annotate")

    def _calibrate_region(self, key: str, annotation: str) -> None:
        if self._calibrating:
            return
        self._calibrating = True
        self._generation += 1
        self._pending = False
        try:
            self.ctx.services.require(RegionApi).request_region(key, self.ctx.tr(annotation), _REGION_COLOR)
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
                str(bundled_loop_path(self.id, "down")),
            )
        )
        section.addCards(
            ConfigSwitchCard(
                self.config.self_down_stop,
                FluentIcon.VIEW,
                tr("settings.self_stop.title"),
            ),
            HotkeySettingCard(
                self.ctx.services.require(HotkeyApi),
                _SELF_CALIBRATE,
                HotkeyBinding(None),
                FluentIcon.SYNC,
                tr("settings.self_region.title"),
                tr("settings.self_region.content"),
                actions=[(tr("settings.region.button"), self._calibrate_self)],
                accessories=[RegionStatus(self.ctx.services, _SELF_REGION_KEY, _REGION_COLOR)],
            ),
            ConfigSwitchCard(
                self.config.three_player_only,
                FluentIcon.PEOPLE,
                tr("settings.three_player_only.title"),
            ),
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
        self.loop_audio.volume.set(10)
        self.loop_audio.fade_in.set(2.0)
        self.loop_audio.fade_out.set(2.0)
        if (regions := self.ctx.services.get(RegionApi)) is not None:
            regions.clear_region(_REGION_KEY)
            regions.clear_region(_SELF_REGION_KEY)
