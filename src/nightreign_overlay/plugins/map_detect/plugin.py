"""Map information plugin: faithful trigger state machine with serialized background detection."""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
from PyQt6.QtCore import QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, PushSettingCard

from nightreign_overlay.core.debug import DebugImageApi
from nightreign_overlay.core.screens import mapping_for_rect
from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.capture.api import CaptureApi, FrameCaptured, crop_rgb, normalize_image
from nightreign_overlay.plugins.day_timer.api import DayStarted
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.plugins.map_detect.api import MapRecognitionApi
from nightreign_overlay.plugins.map_detect.config import MapDetectConfig, MapDetectionSettings
from nightreign_overlay.plugins.map_detect.controls import MapControlsOverlay
from nightreign_overlay.plugins.map_detect.detector import MapDetector, MapDetectParam, MapDetectResult
from nightreign_overlay.plugins.map_detect.localization import load_names
from nightreign_overlay.plugins.map_detect.manual_catalog import ManualFilterCatalog, PoiChoice
from nightreign_overlay.plugins.map_detect.manual_filter import ManualFilterOverlay
from nightreign_overlay.plugins.map_detect.map_info import MapPattern, Position
from nightreign_overlay.plugins.map_detect.overlay import MapInfoOverlay, MapOverlayState
from nightreign_overlay.plugins.map_detect.stability import MapStability, map_stability_sample
from nightreign_overlay.plugins.region.api import RegionApi, RegionStatus
from nightreign_overlay.ui.components import (
    ConfigChoiceCard,
    ConfigDoubleSpinCard,
    ConfigRangeCard,
    HotkeySettingCard,
    SettingSection,
    SettingsPanel,
)
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayManager

_REGION_KEY = "map_detect.map_region"
_REGION_COLOR = "#4384b9"


class _NoopDebugImageApi:
    def save(self, *args: Any, **kwargs: Any) -> bool:
        return False


_ACTIONS = (
    "calibrate_region",
    "recognize",
    "toggle",
    "next_result",
    "previous_result",
    "next_crystal",
    "previous_crystal",
    "manual_filter",
)
_EARTH_SHIFTING_IDS = tuple(range(6))
# Manual filtering can be applied early once this few candidate maps remain.
_MANUAL_APPLY_LIMIT = 5


class MatchFlag(Enum):
    """Clear existing pixels in PREPARE, then wait for stable full-map frames in TRUE."""

    FALSE = 0
    PREPARE = 1
    TRUE = 2


@dataclass(frozen=True)
class _Job:
    generation: int
    region: tuple[int, int, int, int]
    image: np.ndarray
    hdr: bool
    settings: MapDetectionSettings
    topk: int
    stage: str
    captured_at: float
    manual_revision: int = 0
    poi_position: Position | None = None
    earth_shifting: int | None = None
    nightlord: int | None = None
    pattern_ids: tuple[int, ...] = ()


class _RecognitionService(MapRecognitionApi):
    def __init__(self, plugin: MapDetectPlugin) -> None:
        self._plugin = plugin

    def ready(self) -> bool:
        return (
            self._plugin._active
            and not self._plugin._manual_filtering
            and self._plugin._flag != MatchFlag.FALSE
        )


class MapDetectPlugin(Plugin):
    manifest = PluginManifest(
        id="map_detect",
        kind=PluginKind.FEATURE,
        icon="GLOBE",
        requires=("capture", "input", "region"),
        optional=("day_timer",),
        order=30,
    )
    _completed = pyqtSignal(object, object, object)
    _force_display_text_changed = pyqtSignal(str)

    def on_load(self) -> None:
        self.config = self.ctx.config(MapDetectConfig)
        self._window_config = self.ctx.config(OverlayConfig, "window")
        self._window_config.input_mode.set("passthrough")
        self._overlay: MapInfoOverlay | None = None
        self._manual_overlay: ManualFilterOverlay | None = None
        self._controls: MapControlsOverlay | None = None
        self._detector: MapDetector | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._active = False
        self._busy = False
        self._pending_job: _Job | None = None
        self._calibrating = False
        self._generation = 0
        self._region: QRect | None = None
        self._flag = MatchFlag.TRUE
        self._stability = MapStability()
        self._current_is_full_map = False
        self._map_overlay_visible = False
        self._force_display = False
        self._manual_filtering = False
        self._manual_catalog: ManualFilterCatalog | None = None
        self._manual_revision = 0
        self._manual_auto_in_flight = False
        self._manual_capture_in_progress = False
        self._manual_entry_recognition = False
        self._last_match = 0.0
        self._completed.connect(self._on_completed, Qt.ConnectionType.QueuedConnection)

    def on_activate(self) -> None:
        self._active = True
        self._generation += 1
        self._region = None
        self._flag = MatchFlag.PREPARE
        self._stability.reset()
        self._current_is_full_map = self._map_overlay_visible = False
        self._manual_filtering = False
        manager = self.ctx.services.require(OverlayManager)
        self._overlay = MapInfoOverlay(manager, self._window_config, self.ctx.tr)
        self.ctx.on_cleanup(self._overlay.dispose)
        names = load_names(self.ctx.language)
        earth_shiftings = [
            (earth_shifting, names.get(200000 + earth_shifting, str(earth_shifting)))
            for earth_shifting in _EARTH_SHIFTING_IDS
        ]
        nightlords = [(nightlord, names.get(100000 + nightlord, str(nightlord))) for nightlord in range(10)]
        self._manual_overlay = ManualFilterOverlay(manager, self.ctx.tr, earth_shiftings, nightlords)
        self._manual_overlay.earthShiftingChanged.connect(self._on_manual_parameters_changed)
        self._manual_overlay.nightlordChanged.connect(self._on_manual_parameters_changed)
        self._manual_overlay.poiChoiceChanged.connect(self._on_manual_poi_choice)
        self._manual_overlay.autoRecognizeRequested.connect(self._request_manual_auto_recognition)
        self._manual_overlay.applyRequested.connect(self._apply_manual_candidates)
        self.ctx.on_cleanup(self._manual_overlay.dispose)
        self._controls = MapControlsOverlay(
            self._overlay, self._manual_overlay, self.ctx.tr, self._callbacks()
        )
        self.ctx.on_cleanup(self._controls.dispose)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="map-detect")
        self.ctx.on_cleanup(self._stop_worker)
        self.ctx.provide(MapRecognitionApi, _RecognitionService(self))
        self.ctx.subscribe(DayStarted, self._on_day_started)
        self.ctx.subscribe(FrameCaptured, self._on_frame)
        hotkeys = self.ctx.services.require(HotkeyApi)
        for action, callback in self._callbacks().items():
            key = f"{self.id}.{action}"
            hotkeys.register(key, HotkeyBinding(None), callback)
            self.ctx.on_cleanup(lambda key=key: hotkeys.unregister(key))
        capture = self.ctx.services.require(CaptureApi)
        capture.acquire_stream(self.id)
        self.ctx.on_cleanup(lambda: capture.release_stream(self.id))

    def on_deactivate(self) -> None:
        self._set_force_display(False)
        self._active = False
        self._generation += 1
        self._stability.reset()
        self._overlay = None
        self._manual_overlay = None
        self._controls = None
        self._manual_filtering = False
        self._manual_revision += 1
        self._manual_auto_in_flight = False
        self._manual_capture_in_progress = False
        self._manual_entry_recognition = False

    def _stop_worker(self) -> None:
        self._active = False
        self._generation += 1
        self._stability.reset()
        if self._executor is not None:
            # Finish the single running native OpenCV call before disposing its resources.
            self._executor.shutdown(wait=True, cancel_futures=True)
        self._executor = self._detector = None
        self._busy = False

    def _callbacks(self) -> dict[str, Any]:
        return {
            "calibrate_region": self._calibrate_region,
            "recognize": self._request_visible_match,
            "toggle": self._toggle_overlay,
            "next_result": lambda: self._cycle("next_overlay_image"),
            "previous_result": lambda: self._cycle("last_overlay_image"),
            "next_crystal": lambda: self._cycle("next_crystal_layout"),
            "previous_crystal": lambda: self._cycle("last_crystal_layout"),
            "manual_filter": self._toggle_manual_filter,
        }

    def _overlay_accepts_hotkeys(self) -> bool:
        return self._map_overlay_visible and self._overlay is not None and self._overlay.isVisible()

    def _request_visible_match(self) -> None:
        if self._overlay_accepts_hotkeys():
            self._request_match()

    def _request_match(self) -> None:
        if self._manual_filtering:
            return
        self._generation += 1
        self._flag = MatchFlag.PREPARE
        self._stability.reset()
        if self._overlay is not None and self._overlay.map_pattern_matching:
            self._overlay.update_ui_state(MapOverlayState(map_pattern_matching=False))
        self.ctx.log.info("Set to detect map pattern once.")

    def _on_day_started(self, event: DayStarted) -> None:
        if event.day == 1:
            self._request_match()

    def _set_overlay_visible(self, visible: bool) -> None:
        if self._overlay is None or self._region is None:
            return
        visible = visible or self._force_display
        if visible:
            self._overlay.set_map_region(self._region)
        self._overlay.update_ui_state(MapOverlayState(opacity=1.0 if visible else 0.0))
        self._map_overlay_visible = visible

    def _force_display_text(self) -> str:
        action = "exit" if self._force_display else "enter"
        return self.ctx.tr(f"settings.force_display.{action}")

    def _toggle_force_display(self) -> None:
        if not self._active:
            return
        if not self._force_display:
            region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
            if region is None:
                self.ctx.log.warning("Calibrate the map region before enabling forced display.")
                return
            if region != self._region:
                self._region = QRect(region)
                self._request_match()
        self._set_force_display(not self._force_display)

    def _set_force_display(self, enabled: bool) -> None:
        if enabled == self._force_display:
            return
        self._force_display = enabled
        self._force_display_text_changed.emit(self._force_display_text())
        # Display gates are separate from _current_is_full_map and the job state
        # machine. In particular, a failed full-map check must not submit terrain.
        self._set_overlay_visible(self._current_is_full_map)
        if self._manual_overlay is not None:
            self._manual_overlay.set_map_open(self._current_is_full_map or enabled)
        if self._controls is not None:
            self._controls.sync_from_map()

    def _toggle_overlay(self) -> None:
        self._set_overlay_visible(not self._map_overlay_visible)

    def _toggle_manual_filter(self) -> None:
        if self._manual_filtering:
            self._exit_manual_filter()
            return
        if not self._active or self._overlay is None or self._manual_overlay is None:
            return
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        if region is None:
            self.ctx.log.warning("Cannot enter manual map filtering before the map region is calibrated.")
            return
        self._generation += 1
        self._manual_revision += 1
        self._region = QRect(region)
        self._manual_filtering = True
        self._stability.reset()
        if self._manual_catalog is None:
            self._manual_catalog = ManualFilterCatalog.load(self.ctx.language)
        self._manual_overlay.set_catalog(self._manual_catalog)
        self._manual_overlay.reset_selection()
        self._manual_overlay.set_map_region(self._region)
        # The manual filter must be visible immediately while the entry
        # recognition runs in the background.
        self._manual_overlay.set_map_open(True)
        self._overlay.set_suppressed(True)
        self._manual_overlay.show_overlay()
        if self._controls is not None:
            self._controls.set_manual_filtering(True)
        self._start_manual_entry_recognition()

    def _start_manual_entry_recognition(self) -> None:
        if self._manual_entry_recognition or self._manual_overlay is None:
            return
        self._manual_entry_recognition = True
        self._manual_overlay.show_entry_recognizing()
        revision = self._manual_revision
        QTimer.singleShot(150, lambda: self._capture_manual_entry(revision))

    def _capture_manual_entry(self, revision: int) -> None:
        if not self._manual_filtering or revision != self._manual_revision or self._region is None:
            if (
                self._manual_filtering
                and revision == self._manual_revision
                and self._manual_overlay is not None
            ):
                self._manual_overlay.show_select_earth_shifting()
            self._finish_manual_entry_recognition()
            return
        current_region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        if current_region is None or current_region != self._region:
            if self._manual_overlay is not None:
                self._manual_overlay.show_select_earth_shifting()
            self._finish_manual_entry_recognition()
            return
        self._manual_capture_in_progress = True
        self._manual_overlay.set_capture_hidden(True)
        self.ctx.services.require(CaptureApi).request_frame(
            lambda frame: self._on_manual_entry_frame(frame, revision, current_region)
        )

    def _on_manual_entry_frame(self, frame: FrameCaptured | None, revision: int, region: QRect) -> None:
        self._manual_capture_in_progress = False
        if self._manual_overlay is not None:
            self._manual_overlay.set_capture_hidden(False)
        if frame is None or not self._manual_filtering or revision != self._manual_revision:
            if self._manual_overlay is not None:
                self._manual_overlay.show_select_earth_shifting()
            self._finish_manual_entry_recognition()
            return
        image = crop_rgb(frame.image, region)
        if image is None or image.shape[:2] != (region.height(), region.width()):
            if self._manual_overlay is not None:
                self._manual_overlay.show_select_earth_shifting()
            self._finish_manual_entry_recognition()
            return
        self._submit(
            _Job(
                self._generation,
                region.getRect(),
                image,
                frame.hdr,
                self.config.snapshot(),
                self.config.return_topk.value,
                "entry_check",
                frame.captured_at,
                manual_revision=revision,
            )
        )

    def _finish_manual_entry_recognition(self) -> None:
        self._manual_entry_recognition = False
        self._manual_capture_in_progress = False
        if self._manual_overlay is not None:
            self._manual_overlay.set_capture_hidden(False)

    def _exit_manual_filter(self) -> None:
        if not self._manual_filtering:
            return
        self._generation += 1
        self._manual_revision += 1
        self._manual_filtering = False
        self._stability.reset()
        self._manual_auto_in_flight = False
        self._manual_capture_in_progress = False
        if self._manual_overlay is not None:
            self._manual_overlay.set_capture_hidden(False)
            self._manual_overlay.set_auto_recognizing(None)
            self._manual_overlay.close_popup()
            self._manual_overlay.hide_overlay()
        if self._overlay is not None:
            self._overlay.set_suppressed(False)
        if self._controls is not None:
            self._controls.set_manual_filtering(False)

    def _on_manual_parameters_changed(self, _value: object) -> None:
        if not self._manual_filtering or self._manual_overlay is None:
            return
        self._manual_revision += 1
        self._manual_auto_in_flight = False
        self._manual_overlay.clear_poi_choices()
        self._manual_overlay.refresh_positions()
        if self._manual_overlay.earth_shifting is None:
            self._manual_overlay.show_select_earth_shifting()
        else:
            self._rematch_manual_filter()

    def _on_manual_poi_choice(self, pos: Position, choice: PoiChoice) -> None:
        if not self._manual_filtering or self._manual_overlay is None:
            return
        explicit = dict(self._manual_overlay.explicit_choices)
        explicit[pos] = choice
        self._manual_overlay.set_filter_state(explicit, {})
        self._rematch_manual_filter()

    def _rematch_manual_filter(self) -> None:
        overlay = self._manual_overlay
        catalog = self._manual_catalog
        if not self._manual_filtering or overlay is None or catalog is None:
            return
        earth_shifting = overlay.earth_shifting
        if earth_shifting is None:
            overlay.set_filter_state(overlay.explicit_choices, {})
            overlay.show_select_earth_shifting()
            return
        candidates = catalog.candidates(earth_shifting, overlay.nightlord, overlay.explicit_choices)
        if not candidates:
            self._manual_revision += 1
            self._manual_auto_in_flight = False
            overlay.clear_poi_choices()
            overlay.refresh_positions()
            overlay.show_no_match()
            return
        if len(candidates) == 1:
            self._finish_manual_filter(candidates, overlay.nightlord)
            return
        inferred = catalog.inferred(
            candidates,
            catalog.positions(earth_shifting, overlay.nightlord),
            overlay.explicit_choices,
        )
        overlay.set_filter_state(overlay.explicit_choices, inferred)
        overlay.show_candidate_count(len(candidates), len(candidates) <= _MANUAL_APPLY_LIMIT)

    def _apply_manual_candidates(self) -> None:
        overlay = self._manual_overlay
        catalog = self._manual_catalog
        if not self._manual_filtering or overlay is None or catalog is None or overlay.earth_shifting is None:
            return
        candidates = catalog.candidates(overlay.earth_shifting, overlay.nightlord, overlay.explicit_choices)
        if 0 < len(candidates) <= _MANUAL_APPLY_LIMIT:
            self._finish_manual_filter(candidates, overlay.nightlord)

    def _request_manual_auto_recognition(self, pos: Position) -> None:
        overlay = self._manual_overlay
        if (
            self._manual_auto_in_flight
            or not self._active
            or not self._manual_filtering
            or overlay is None
            or not overlay.map_open
            or overlay.earth_shifting is None
        ):
            return
        self._manual_auto_in_flight = True
        overlay.close_popup()
        overlay.set_auto_recognizing(pos)
        overlay.set_capture_hidden(True)
        revision = self._manual_revision
        QTimer.singleShot(150, lambda: self._capture_manual_poi(pos, revision))

    def _capture_manual_poi(self, pos: Position, revision: int) -> None:
        overlay = self._manual_overlay
        if (
            not self._active
            or not self._manual_filtering
            or revision != self._manual_revision
            or overlay is None
            or not overlay.map_open
            or overlay.earth_shifting is None
        ):
            self._abort_manual_auto_recognition()
            return
        current_region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        if current_region is None or self._region is None or current_region != self._region:
            self.ctx.log.warning("Manual POI recognition aborted because the map region changed.")
            self._abort_manual_auto_recognition()
            return

        self._manual_capture_in_progress = True
        self.ctx.services.require(CaptureApi).request_frame(
            lambda frame: self._on_manual_frame(frame, pos, revision, current_region)
        )

    def _on_manual_frame(
        self, frame: FrameCaptured | None, pos: Position, revision: int, current_region: QRect
    ) -> None:
        if revision != self._manual_revision:
            return
        self._manual_capture_in_progress = False
        overlay = self._manual_overlay
        if overlay is not None:
            overlay.set_capture_hidden(False)
        if (
            not self._active
            or not self._manual_filtering
            or overlay is None
            or not overlay.map_open
            or overlay.earth_shifting is None
        ):
            self._abort_manual_auto_recognition()
            return
        if frame is None:
            self.ctx.log.warning("Manual POI recognition capture returned no image.")
            self._abort_manual_auto_recognition()
            return
        image = crop_rgb(frame.image, current_region)
        if image is None or image.shape[:2] != (current_region.height(), current_region.width()):
            self.ctx.log.warning("Manual POI recognition capture did not match the map region.")
            self._abort_manual_auto_recognition()
            return
        self._submit(
            _Job(
                self._generation,
                current_region.getRect(),
                image,
                frame.hdr,
                self.config.snapshot(),
                self.config.return_topk.value,
                "poi",
                captured_at=frame.captured_at,
                manual_revision=revision,
                poi_position=pos,
                earth_shifting=overlay.earth_shifting,
                nightlord=overlay.nightlord,
            )
        )

    def _abort_manual_auto_recognition(self) -> None:
        self._manual_auto_in_flight = False
        self._manual_capture_in_progress = False
        if self._manual_overlay is not None:
            self._manual_overlay.set_capture_hidden(False)
            self._manual_overlay.set_auto_recognizing(None)

    def _complete_manual_auto_recognition(self, job: _Job, result: MapDetectResult) -> None:
        overlay = self._manual_overlay
        catalog = self._manual_catalog
        if (
            not self._manual_filtering
            or job.manual_revision != self._manual_revision
            or overlay is None
            or catalog is None
            or job.poi_position is None
        ):
            self._abort_manual_auto_recognition()
            return
        ctype = (result.poi_types or {}).get(job.poi_position)
        if ctype is None:
            self.ctx.log.warning("Manual POI recognition returned no type for %s.", job.poi_position)
            self._abort_manual_auto_recognition()
            return
        explicit = dict(overlay.explicit_choices)
        explicit[job.poi_position] = catalog.choice_from_ctype(ctype)
        self._manual_auto_in_flight = False
        overlay.set_filter_state(explicit, {})
        self._rematch_manual_filter()

    def _finish_manual_filter(self, patterns: list[MapPattern], nightlord: int | None) -> None:
        if self._overlay is None or self._region is None:
            return
        patterns = sorted(patterns, key=lambda pattern: pattern.id)
        earth_shifting = patterns[0].earth_shifting
        region = QRect(self._region)
        self._exit_manual_filter()
        self._flag = MatchFlag.FALSE
        self._last_match = time.monotonic()
        self._map_overlay_visible = self._current_is_full_map or self._force_display
        self._overlay.set_map_region(region)
        self._overlay.update_ui_state(
            MapOverlayState(
                clear_image=True,
                map_pattern_matching=True,
                opacity=1.0 if self._map_overlay_visible else 0.0,
                display_crystal_layout=False,
            )
        )
        self._submit(
            _Job(
                self._generation,
                region.getRect(),
                np.empty((0, 0, 3), dtype=np.uint8),
                False,
                self.config.snapshot(),
                self.config.return_topk.value,
                "draw",
                captured_at=time.monotonic(),
                earth_shifting=earth_shifting,
                nightlord=nightlord,
                pattern_ids=tuple(pattern.id for pattern in patterns),
            )
        )

    def _cycle(self, method: str) -> None:
        if self._overlay_accepts_hotkeys():
            getattr(self._overlay, method)()

    def _on_frame(self, frame: FrameCaptured) -> None:
        if not self._active or self._calibrating or self._manual_capture_in_progress:
            return
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        if self._manual_filtering:
            if region is None:
                self._exit_manual_filter()
                return
            if region != self._region:
                self._region = QRect(region)
                if self._manual_overlay is not None:
                    self._manual_overlay.set_map_region(self._region)
        if region != self._region:
            self._region = QRect(region) if region is not None else None
            self._request_match()
            if self._force_display and region is not None:
                self._set_overlay_visible(True)
        if region is None:
            self._stability.reset()
            if self._overlay is not None:
                self._overlay.update_ui_state(
                    MapOverlayState(opacity=0.0, clear_image=True, display_crystal_layout=False)
                )
            self._map_overlay_visible = self._current_is_full_map = False
            return
        if self._busy:
            return
        image = crop_rgb(frame.image, region)
        if image is None or image.shape[:2] != (region.height(), region.width()):
            self._stability.reset()
            return
        self._submit(
            _Job(
                self._generation,
                region.getRect(),
                image,
                frame.hdr,
                self.config.snapshot(),
                self.config.return_topk.value,
                "check",
                captured_at=frame.captured_at,
            )
        )

    def _submit(self, job: _Job) -> None:
        if self._executor is None:
            return
        self._busy = True
        self._pending_job = job
        future = self._executor.submit(self._run_job, job)
        future.add_done_callback(lambda result: self._deliver(job, result))

    def _deliver(self, job: _Job, future: Future[MapDetectResult]) -> None:
        try:
            self._completed.emit(job, future.result(), None)
        except Exception as exc:
            self._completed.emit(job, None, exc)

    def _run_job(self, job: _Job) -> MapDetectResult:
        # Only this single worker accesses detector caches. No Qt object is read or mutated here.
        if self._detector is None:
            self._detector = MapDetector(job.settings, language=self.ctx.language)
        self._detector.config = job.settings
        image = (
            normalize_image(job.image)
            if job.hdr and job.stage in ("check", "entry_check", "poi")
            else job.image
        )
        if job.stage in ("check", "entry_check"):
            return self._detector.detect(
                MapDetectParam(map_region=job.region, img=image, do_match_full_map=True)
            )
        if job.stage in ("terrain", "entry_terrain"):
            return self._detector.detect(
                MapDetectParam(map_region=job.region, img=image, do_match_earth_shifting=True)
            )
        if job.stage == "poi":
            return self._detector.detect(
                MapDetectParam(
                    map_region=job.region,
                    img=image,
                    earth_shifting=job.earth_shifting,
                    poi_positions=[job.poi_position],
                    nightlord=job.nightlord,
                )
            )
        if job.stage == "draw":
            return self._detector.detect(
                MapDetectParam(
                    map_region=job.region,
                    draw_pattern_ids=list(job.pattern_ids),
                    nightlord=job.nightlord,
                )
            )
        return self._detector.detect(
            MapDetectParam(
                map_region=job.region,
                img=image,
                earth_shifting=job.earth_shifting if job.stage == "entry_boss" else int(job.stage),
                do_match_pattern=True,
                return_pattern_topk=job.topk,
            )
        )

    def _on_completed(self, job: _Job, result: MapDetectResult | None, error: Exception | None) -> None:
        # A result queued before hot reactivation must not clear the new activation's busy flag.
        if not self._active or job is not self._pending_job:
            return
        self._busy = False
        self._pending_job = None
        if job.generation != self._generation or self._overlay is None:
            return
        current_region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        if current_region is None or current_region.getRect() != job.region:
            if job.stage.startswith("entry_"):
                if self._manual_overlay is not None:
                    self._manual_overlay.show_select_earth_shifting()
                self._finish_manual_entry_recognition()
            elif job.stage == "poi":
                self._abort_manual_auto_recognition()
            else:
                self._request_match()
            return
        if error is not None or result is None:
            self._stability.reset()
            self.ctx.log.error("Map detection failed in %s: %s", job.stage, error)
            self._overlay.update_ui_state(MapOverlayState(map_pattern_matching=False))
            if job.stage == "poi" and self._manual_overlay is not None:
                self._manual_auto_in_flight = False
                self._manual_overlay.set_auto_recognizing(None)
            if job.stage.startswith("entry_"):
                if self._manual_overlay is not None:
                    self._manual_overlay.show_select_earth_shifting()
                self._finish_manual_entry_recognition()
            return
        if job.stage == "entry_check":
            if not result.is_full_map:
                if self._manual_overlay is not None:
                    self._manual_overlay.show_select_earth_shifting()
                self._finish_manual_entry_recognition()
            else:
                if self._manual_overlay is not None:
                    self._manual_overlay.set_map_open(True)
                self._submit(
                    _Job(
                        self._generation,
                        job.region,
                        job.image,
                        job.hdr,
                        job.settings,
                        job.topk,
                        "entry_terrain",
                        job.captured_at,
                        manual_revision=job.manual_revision,
                    )
                )
            return
        if job.stage == "entry_terrain":
            if result.earth_shifting is None:
                if self._manual_overlay is not None:
                    self._manual_overlay.show_select_earth_shifting()
                self._finish_manual_entry_recognition()
            else:
                if self._manual_overlay is not None:
                    self._manual_overlay.set_recognized_parameters(result.earth_shifting, None)
                self._submit(
                    _Job(
                        self._generation,
                        job.region,
                        job.image,
                        job.hdr,
                        job.settings,
                        job.topk,
                        "entry_boss",
                        job.captured_at,
                        manual_revision=job.manual_revision,
                        earth_shifting=result.earth_shifting,
                    )
                )
            return
        if job.stage == "entry_boss":
            if self._manual_overlay is not None:
                self._manual_overlay.set_recognized_parameters(job.earth_shifting, result.nightlord)
                self._rematch_manual_filter()
            self._finish_manual_entry_recognition()
            return
        debug = self.ctx.services.get(DebugImageApi)
        if debug is None:
            debug = _NoopDebugImageApi()
        if job.stage == "check":
            debug.save(
                "map_full_map",
                job.image,
                {"is_full_map": result.is_full_map, "score": result.full_map_score, "region": job.region},
                cooldown_seconds=600,
            )
        elif job.stage == "terrain":
            debug.save(
                "map_terrain",
                job.image,
                {
                    "earth_shifting": result.earth_shifting,
                    "score": result.earth_shifting_score,
                    "region": job.region,
                },
            )
        elif job.stage == "poi":
            for name, image in (result.debug_images or {}).items():
                debug.save(
                    name,
                    image,
                    {"poi_types": result.poi_types, "poi_scores": result.poi_scores, "region": job.region},
                )
        elif job.stage.isdigit():
            debug.save(
                "map_nightlord",
                job.image,
                {"nightlord": result.nightlord, "score": result.nightlord_score, "region": job.region},
            )
            for name, image in (result.debug_images or {}).items():
                debug.save(
                    name,
                    image,
                    {
                        "earth_shifting": job.earth_shifting,
                        "nightlord": result.nightlord,
                        "nightlord_score": result.nightlord_score,
                        "patterns": [pattern.id for pattern in result.patterns or []],
                        "region": job.region,
                    },
                )
        if job.stage == "poi":
            self._complete_manual_auto_recognition(job, result)
        elif job.stage == "draw":
            self._last_match = time.monotonic()
            self._overlay.update_ui_state(
                MapOverlayState(
                    overlay_images=result.overlay_images,
                    map_pattern_match_time=time.time(),
                    map_pattern_matching=False,
                    display_crystal_layout=(job.earth_shifting == 4),
                )
            )
        elif job.stage == "check":
            full_map = bool(result.is_full_map)
            if full_map != self._current_is_full_map:
                self._current_is_full_map = full_map
                self._set_overlay_visible(full_map)
            if self._manual_filtering:
                if self._manual_overlay is not None:
                    self._manual_overlay.set_map_open(full_map or self._force_display)
                return
            now = time.monotonic()
            if now - self._last_match > self.config.map_pattern_match_interval.value:
                self._request_match()
                self._last_match = now
            if self._flag == MatchFlag.PREPARE:
                self._flag = MatchFlag.TRUE
                self._stability.reset()
                self._overlay.update_ui_state(
                    MapOverlayState(
                        clear_image=True,
                        map_pattern_match_time=0,
                        map_pattern_matching=False,
                        display_crystal_layout=False,
                    )
                )
            elif self._flag == MatchFlag.TRUE:
                # Compare raw pixels: HDR normalization can erase the fade's
                # luminance changes. Reuse the newest normalized image only
                # after its capture history confirms that the map is stable.
                sample = map_stability_sample(job.image) if full_map else None
                if self._stability.observe(
                    sample,
                    job.captured_at,
                    full_map,
                    job.settings.map_stability_change_threshold,
                    job.settings.map_stability_duration,
                ):
                    self._submit(
                        _Job(
                            self._generation,
                            job.region,
                            result.img,
                            False,
                            job.settings,
                            job.topk,
                            "terrain",
                            captured_at=job.captured_at,
                        )
                    )
        elif job.stage == "terrain":
            if result.earth_shifting is not None:
                self._flag = MatchFlag.FALSE
                self._stability.reset()
                self._overlay.set_map_region(QRect(*job.region))
                self._overlay.update_ui_state(
                    MapOverlayState(clear_image=True, map_pattern_matching=True, opacity=1.0)
                )
                self._submit(
                    _Job(
                        self._generation,
                        job.region,
                        result.img,
                        False,
                        job.settings,
                        job.topk,
                        str(result.earth_shifting),
                        captured_at=job.captured_at,
                    )
                )
        else:
            self._last_match = time.monotonic()
            self._overlay.update_ui_state(
                MapOverlayState(
                    overlay_images=result.overlay_images,
                    map_pattern_match_time=time.time(),
                    map_pattern_matching=False,
                    display_crystal_layout=(int(job.stage) == 4),
                )
            )

    def _calibrate_region(self) -> None:
        if self._calibrating:
            return
        self._calibrating = True
        self._generation += 1
        self._stability.reset()
        rect = None
        try:
            regions = self.ctx.services.require(RegionApi)
            rect = regions.request_region(
                _REGION_KEY,
                self.ctx.tr("settings.calibrate_region.annotate"),
                _REGION_COLOR,
            )
            if rect is not None:
                # Legacy clamps to a square at the selected top-left, rather than recentering.
                side = min(rect.width(), rect.height())
                ratio = mapping_for_rect(rect, QGuiApplication.screens()).ratio
                # Preserve the old truncation to whole logical pixels at fractional DPI.
                side = int(int(side / ratio) * ratio)
                rect = QRect(rect.x(), rect.y(), side, side)
                regions.save_region(_REGION_KEY, rect)
                self._region = rect
        finally:
            self._calibrating = False
            # Canceling an idle selector leaves existing information intact. If
            # selection invalidated a running pattern job, rearm its lost result.
            if rect is not None or (self._overlay is not None and self._overlay.map_pattern_matching):
                self._request_match()

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        panel = SettingsPanel(parent)
        basic = SettingSection(self.ctx.tr("settings.basic"))
        shortcuts = SettingSection(self.ctx.tr("settings.hotkeys"))
        hotkeys = self.ctx.services.require(HotkeyApi)
        for action, callback in self._callbacks().items():
            calibrate = action == "calibrate_region"
            section = basic if calibrate else shortcuts
            section.addCards(
                HotkeySettingCard(
                    hotkeys,
                    f"{self.id}.{action}",
                    HotkeyBinding(None),
                    FluentIcon.FILTER if action == "manual_filter" else FluentIcon.GLOBE,
                    self.ctx.tr(f"settings.{action}.title"),
                    self.ctx.tr(f"settings.{action}.content"),
                    actions=[(self.ctx.tr("settings.calibrate_region.action"), callback)]
                    if calibrate
                    else [],
                    accessories=[RegionStatus(self.ctx.services, _REGION_KEY, _REGION_COLOR)]
                    if calibrate
                    else [],
                )
            )
        force_display = PushSettingCard(
            self._force_display_text(),
            FluentIcon.GLOBE,
            self.ctx.tr("settings.force_display.title"),
            self.ctx.tr("settings.force_display.content"),
        )
        force_display.button.clicked.connect(self._toggle_force_display)
        self._force_display_text_changed.connect(force_display.button.setText)
        basic.addCards(
            force_display,
            ConfigRangeCard(
                self.config.return_topk,
                FluentIcon.GLOBE,
                self.ctx.tr("settings.topk.title"),
                self.ctx.tr("settings.topk.content"),
            ),
            ConfigRangeCard(
                self.config.english_text_width_percent,
                FluentIcon.FONT,
                self.ctx.tr("settings.english_text_width.title"),
                self.ctx.tr("settings.english_text_width.content"),
                formatter=lambda value: f"{value}%",
            ),
        )
        panel.addSection(basic)
        panel.addSection(shortcuts)
        advanced = SettingSection(self.ctx.tr("settings.advanced"))
        advanced.addCards(
            ConfigChoiceCard(
                self.config.earth_shifting_algorithm,
                [
                    (algorithm, self.ctx.tr(f"settings.earth_shifting_algorithm.{algorithm}"))
                    for algorithm in self.config.earth_shifting_algorithm.option.choices
                ],
                FluentIcon.GLOBE,
                self.ctx.tr("settings.earth_shifting_algorithm.title"),
                self.ctx.tr("settings.earth_shifting_algorithm.content"),
            ),
            ConfigChoiceCard(
                self.config.poi_algorithm,
                [
                    (algorithm, self.ctx.tr(f"settings.poi_algorithm.{algorithm}"))
                    for algorithm in self.config.poi_algorithm.option.choices
                ],
                FluentIcon.GLOBE,
                self.ctx.tr("settings.poi_algorithm.title"),
                self.ctx.tr("settings.poi_algorithm.content"),
            ),
            ConfigRangeCard(
                self.config.map_pattern_match_interval,
                FluentIcon.HISTORY,
                self.ctx.tr("settings.match_interval.title"),
                self.ctx.tr("settings.match_interval.content"),
                formatter=lambda value: f"{value}s",
            ),
            ConfigDoubleSpinCard(
                self.config.full_map_error_threshold,
                FluentIcon.DEVELOPER_TOOLS,
                self.ctx.tr("settings.full_map_error_threshold.title"),
                self.ctx.tr("settings.full_map_error_threshold.content"),
                decimals=1,
                step=1.0,
                formatter=lambda value: f"{value:g}",
            ),
            ConfigDoubleSpinCard(
                self.config.map_stability_change_threshold,
                FluentIcon.DEVELOPER_TOOLS,
                self.ctx.tr("settings.map_stability_change_threshold.title"),
                self.ctx.tr("settings.map_stability_change_threshold.content"),
                decimals=1,
                step=0.5,
                formatter=lambda value: f"{value:g}",
            ),
            ConfigDoubleSpinCard(
                self.config.map_stability_duration,
                FluentIcon.HISTORY,
                self.ctx.tr("settings.map_stability_duration.title"),
                self.ctx.tr("settings.map_stability_duration.content"),
                decimals=2,
                step=0.05,
                formatter=lambda value: f"{value:.2f}s",
            ),
            ConfigDoubleSpinCard(
                self.config.earth_shifting_ncc_threshold,
                FluentIcon.DEVELOPER_TOOLS,
                self.ctx.tr("settings.earth_shifting_ncc_threshold.title"),
                self.ctx.tr("settings.earth_shifting_ncc_threshold.content"),
                decimals=3,
                step=0.01,
                formatter=lambda value: f"{value:.3f}",
            ),
            ConfigDoubleSpinCard(
                self.config.earth_shifting_error_threshold,
                FluentIcon.DEVELOPER_TOOLS,
                self.ctx.tr("settings.earth_shifting_error_threshold.title"),
                self.ctx.tr("settings.earth_shifting_error_threshold.content"),
                decimals=1,
                step=1.0,
                formatter=lambda value: f"{value:g}",
            ),
            ConfigDoubleSpinCard(
                self.config.subicon_template_match_threshold,
                FluentIcon.DEVELOPER_TOOLS,
                self.ctx.tr("settings.subicon_template_match_threshold.title"),
                self.ctx.tr("settings.subicon_template_match_threshold.content"),
                decimals=3,
                step=0.001,
                formatter=lambda value: f"{value:.3f}",
            ),
            ConfigDoubleSpinCard(
                self.config.poi_match_sample_ratio_w_nightlord,
                FluentIcon.DEVELOPER_TOOLS,
                self.ctx.tr("settings.poi_match_sample_ratio_w_nightlord.title"),
                self.ctx.tr("settings.poi_match_sample_ratio_w_nightlord.content"),
                decimals=2,
                step=0.05,
                formatter=lambda value: f"{value:.2f}",
            ),
            ConfigDoubleSpinCard(
                self.config.poi_match_sample_ratio_wo_nightlord,
                FluentIcon.DEVELOPER_TOOLS,
                self.ctx.tr("settings.poi_match_sample_ratio_wo_nightlord.title"),
                self.ctx.tr("settings.poi_match_sample_ratio_wo_nightlord.content"),
                decimals=2,
                step=0.05,
                formatter=lambda value: f"{value:.2f}",
            ),
        )
        panel.addSection(advanced)
        return panel

    def reset_settings(self) -> None:
        self._set_force_display(False)
        super().reset_settings()
        self._window_config.input_mode.set("passthrough")
        hotkeys = self.ctx.services.require(HotkeyApi)
        for action in _ACTIONS:
            hotkeys.set_binding(f"{self.id}.{action}", HotkeyBinding(None))
        if (regions := self.ctx.services.get(RegionApi)) is not None:
            regions.clear_region(_REGION_KEY)
        self._exit_manual_filter()
        self._request_match()
