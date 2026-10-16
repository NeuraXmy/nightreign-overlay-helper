"""Continuous raw-frame HP-border detection with a serialized worker and an independent overlay."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.core.debug import DebugImageApi
from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.capture.api import CaptureApi, FrameCaptured, crop_rgb
from nightreign_overlay.plugins.hp_marker.config import HpDetectionSettings, HpMarkerConfig
from nightreign_overlay.plugins.hp_marker.detector import HpDetector
from nightreign_overlay.plugins.hp_marker.overlay import HpMarkerOverlay
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.plugins.region.api import RegionApi, RegionStatus
from nightreign_overlay.ui.components import (
    ConfigChoiceCard,
    ConfigColorCard,
    ConfigDoubleSpinCard,
    ConfigRangeCard,
    HotkeySettingCard,
    SettingSection,
    SettingsPanel,
)
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayManager

_REGION_KEY = "hp_marker.hpbar_region"
_CALIBRATE = "hp_marker.calibrate_region"
_REGION_COLOR = "#eb3b3b"


@dataclass(frozen=True)
class _Job:
    generation: int
    region: QRect
    image: np.ndarray
    settings: HpDetectionSettings


class HpMarkerPlugin(Plugin):
    manifest = PluginManifest(
        id="hp_marker",
        kind=PluginKind.FEATURE,
        icon="HEART",
        requires=("capture", "input", "region"),
        order=40,
    )
    _completed = pyqtSignal(object, object, object)

    def on_load(self) -> None:
        self.config = self.ctx.config(HpMarkerConfig)
        self._window_config = self.ctx.config(OverlayConfig, "window")
        self._window_config.input_mode.set("passthrough")
        self._overlay: HpMarkerOverlay | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._detector: HpDetector | None = None
        self._pending: _Job | None = None
        self._active = False
        self._calibrating = False
        self._generation = 0
        self._region: QRect | None = None
        self._worker_generation: int | None = None
        self.config.detection_algorithm.valueChanged.connect(self._on_algorithm_changed)
        self._completed.connect(self._on_completed, Qt.ConnectionType.QueuedConnection)

    def on_activate(self) -> None:
        self._generation += 1
        self._active = True
        self._region = None
        self._detector = HpDetector()
        self._overlay = HpMarkerOverlay(
            self.ctx.services.require(OverlayManager), self._window_config, self.config, self.name
        )
        self.ctx.on_cleanup(self._overlay.dispose)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hp-marker")
        self.ctx.on_cleanup(self._stop_worker)
        self.ctx.subscribe(FrameCaptured, self._on_frame)
        hotkeys = self.ctx.services.require(HotkeyApi)
        hotkeys.register(_CALIBRATE, HotkeyBinding(None), self._calibrate_region)
        self.ctx.on_cleanup(lambda: hotkeys.unregister(_CALIBRATE))
        capture = self.ctx.services.require(CaptureApi)
        capture.acquire_stream(self.id)
        self.ctx.on_cleanup(lambda: capture.release_stream(self.id))

    def on_deactivate(self) -> None:
        self._active = False
        self._generation += 1
        self._overlay = None

    def _stop_worker(self) -> None:
        self._active = False
        self._generation += 1
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
        self._executor = self._detector = self._pending = None

    def _on_frame(self, frame: FrameCaptured) -> None:
        if not self._active or self._calibrating:
            return
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        if region != self._region:
            self._region = QRect(region) if region is not None else None
            self._generation += 1
            if region is None and self._overlay is not None:
                self._overlay.hide_overlay()
        if region is None or self._pending is not None:
            return
        settings = self.config.snapshot()
        # Both algorithms use the full bar height and right-side context.
        expanded = QRect(
            region.x(), region.y(), region.height() * settings.hpbar_region_aspect_ratio, region.height()
        )
        image = crop_rgb(frame.image, expanded)
        if image is None:
            return
        job = _Job(self._generation, QRect(region), image, settings)
        self._pending = job
        future = self._executor.submit(self._run_job, job)
        future.add_done_callback(lambda result: self._deliver(job, result))

    def _on_algorithm_changed(self, _value: str) -> None:
        # In-flight results must not update the overlay after a selection change.
        self._generation += 1

    def _run_job(self, job: _Job) -> int | None:
        # Only the serialized worker mutates the detector, including history resets.
        if self._worker_generation != job.generation:
            self._detector = HpDetector()
            self._worker_generation = job.generation
        return self._detector.detect(job.image, job.settings)

    def _deliver(self, job: _Job, future: Future[int | None]) -> None:
        try:
            self._completed.emit(job, future.result(), None)
        except Exception as exc:
            self._completed.emit(job, None, exc)

    def _on_completed(self, job: _Job, length: int | None, error: Exception | None) -> None:
        if not self._active or job is not self._pending:
            return
        self._pending = None
        if job.generation != self._generation or self._overlay is None:
            return
        if self.ctx.services.require(RegionApi).region(_REGION_KEY) != job.region:
            return
        if error is not None:
            self.ctx.log.error("HP detection failed: %s", error)
            return
        debug = self.ctx.services.get(DebugImageApi)
        if debug is not None:
            debug.save(
                "hp_marker",
                job.image,
                {"detected_length": length, "region": job.region, "settings": job.settings.__dict__},
                cooldown_seconds=600,
            )
        # Rejection leaves the previous display untouched until a clear boundary is found.
        if length is not None:
            if length <= 0:
                self._overlay.hide_overlay()
            else:
                self._overlay.set_hp_region(
                    QRect(job.region.x(), job.region.y(), length, job.region.height())
                )

    def _calibrate_region(self) -> None:
        if self._calibrating:
            return
        self._calibrating = True
        self._generation += 1
        try:
            self.ctx.services.require(RegionApi).request_region(
                _REGION_KEY,
                self.ctx.tr("settings.region.annotate"),
                _REGION_COLOR,
            )
        finally:
            self._calibrating = False

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        tr = self.ctx.tr
        panel = SettingsPanel(parent)
        basic = SettingSection(tr("settings.basic"))
        basic.addCards(
            ConfigChoiceCard(
                self.config.detection_algorithm,
                [
                    (algorithm, tr(f"settings.detection_algorithm.{algorithm}"))
                    for algorithm in self.config.detection_algorithm.option.choices
                ],
                FluentIcon.HEART,
                tr("settings.detection_algorithm.title"),
                tr("settings.detection_algorithm.content"),
            ),
            HotkeySettingCard(
                self.ctx.services.require(HotkeyApi),
                _CALIBRATE,
                HotkeyBinding(None),
                FluentIcon.SYNC,
                tr("settings.region.title"),
                tr("settings.region.content"),
                actions=[(tr("settings.region.button"), self._calibrate_region)],
                accessories=[RegionStatus(self.ctx.services, _REGION_KEY, _REGION_COLOR)],
            ),
            ConfigRangeCard(
                self.config.marker_size,
                FluentIcon.HEART,
                tr("settings.marker_size.title"),
                tr("settings.marker_size.content"),
            ),
            ConfigColorCard(self.config.marker_color, FluentIcon.PALETTE, tr("settings.marker_color.title")),
        )
        advanced = SettingSection(tr("settings.advanced"))
        advanced.addCards(
            *(
                ConfigDoubleSpinCard(
                    self.config.item(name),
                    FluentIcon.HEART,
                    tr(f"settings.{name}.title"),
                    tr(f"settings.{name}.content"),
                    step=0.01,
                )
                for name in ("hpbar_low_hp_marker", "hpbar_high_hp_marker")
            ),
            *(
                ConfigRangeCard(
                    self.config.item(name),
                    FluentIcon.DEVELOPER_TOOLS,
                    tr(f"settings.{name}.title"),
                    tr(f"settings.{name}.content"),
                )
                for name in (
                    "line_width",
                    "line_height",
                    "hpbar_region_aspect_ratio",
                    "hpbar_detect_std_height",
                    "hpbar_border_v_peak_start",
                    "hpbar_border_v_peak_lower",
                    "hpbar_border_v_peak_threshold",
                    "hpbar_border_v_peak_interval",
                    "hpbar_recent_length_count",
                )
            ),
        )
        panel.addSection(basic)
        panel.addSection(advanced)
        return panel

    def reset_settings(self) -> None:
        super().reset_settings()
        self._window_config.input_mode.set("passthrough")
        self.ctx.services.require(HotkeyApi).set_binding(_CALIBRATE, HotkeyBinding(None))
        if (regions := self.ctx.services.get(RegionApi)) is not None:
            regions.clear_region(_REGION_KEY)
        self._generation += 1
        if self._overlay is not None:
            self._overlay.hide_overlay()
