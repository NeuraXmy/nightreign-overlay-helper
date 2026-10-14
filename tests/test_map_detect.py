"""Map orchestration tests; actual screen recognition still needs game captures."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import numpy as np
import pytest
from PIL import Image
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QWidget

from conftest import process_events
from feature_fakes import FeatureServices, solid_image
from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.game_window import GameWindowMonitor
from nightreign_overlay.core.input import InputDevice
from nightreign_overlay.plugins.capture.api import FrameCaptured
from nightreign_overlay.plugins.day_timer.api import DayStarted
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.plugins.map_detect import plugin as module
from nightreign_overlay.plugins.map_detect.api import MapRecognitionApi
from nightreign_overlay.plugins.map_detect.detector import MapDetectResult
from nightreign_overlay.plugins.map_detect.plugin import MapDetectPlugin, MatchFlag, _Job
from nightreign_overlay.ui.components import ConfigDoubleSpinCard
from nightreign_overlay.ui.overlay import OverlayManager
from test_overlay import FakeBackend

_REGION = "map_detect.map_region"
_ROOT = Path(module.__file__).parent


@pytest.fixture
def maps(store, tmp_path, monkeypatch):
    fakes = FeatureServices(store, tmp_path)
    backend = FakeBackend()
    manager = OverlayManager(backend, store.bind(AppConfig, "app"), GameWindowMonitor(backend, fakes.events))
    fakes.services.register(OverlayManager, manager)
    plugin = MapDetectPlugin(fakes.context("map_detect", _ROOT))
    plugin.on_load()
    clock = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    yield plugin, fakes, manager, clock
    plugin.on_deactivate()
    plugin.ctx.release()
    fakes.input.ctx.release()


def _job(plugin, stage="check"):
    return _Job(
        plugin._generation,
        (0, 0, 100, 100),
        np.zeros((100, 100, 3), np.uint8),
        False,
        plugin.config.snapshot(),
        5,
        stage,
    )


def _finish(plugin, job, result):
    plugin._pending_job = job
    plugin._busy = True
    plugin._on_completed(job, result, None)


def _ready(maps, monkeypatch):
    plugin, fakes, _, _ = maps
    plugin.on_activate()
    fakes.region.regions[_REGION] = plugin._region = QRect(0, 0, 100, 100)
    submitted = []
    monkeypatch.setattr(plugin, "_submit", submitted.append)
    return plugin, fakes, submitted


def test_lifecycle_settings_and_resources(maps):
    plugin, fakes, manager, _ = maps
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)
    assert panel is not None
    advanced = {card.item.key: card for card in panel.findChildren(ConfigDoubleSpinCard)}
    assert set(advanced) == {
        "full_map_error_threshold",
        "earth_shifting_error_threshold",
        "subicon_template_match_threshold",
        "poi_match_sample_ratio_w_nightlord",
        "poi_match_sample_ratio_wo_nightlord",
    }
    advanced["subicon_template_match_threshold"].spinBox.setValue(0.123)
    assert plugin.config.subicon_template_match_threshold.value == pytest.approx(0.123)
    plugin.config.subicon_template_match_threshold.reset()
    assert advanced["subicon_template_match_threshold"].spinBox.value() == pytest.approx(0.06)
    assert plugin.config.snapshot().subicon_template_match_threshold == pytest.approx(0.06)
    plugin.on_activate()
    overlay = plugin._overlay
    assert overlay is not None and len(overlay.crystal_layout_imgs) == 5
    assert not overlay.isVisible()
    assert manager.windows() == [overlay]
    assert fakes.capture.streams == {plugin.id}
    assert fakes.services.require(MapRecognitionApi).ready()
    hotkeys = fakes.services.require(HotkeyApi)
    for action in module._ACTIONS:
        assert hotkeys.binding(f"map_detect.{action}", HotkeyBinding(None)) == HotkeyBinding(None)
    plugin.on_deactivate()
    plugin.ctx.release()
    assert not overlay._timer.isActive()
    assert manager.windows() == [] and fakes.capture.streams == set()
    assert fakes.services.get(MapRecognitionApi) is None


def test_prepare_clears_then_reuses_snapshot_for_terrain_and_pattern(maps, monkeypatch):
    plugin, _, submitted = _ready(maps, monkeypatch)
    overlay = plugin._overlay
    overlay.set_overlay_images([Image.new("RGBA", (10, 10))])
    job = _job(plugin)
    _finish(plugin, job, MapDetectResult(img=job.image, is_full_map=True))
    assert plugin._flag == MatchFlag.TRUE and overlay.overlay_images is None
    assert submitted == []
    _finish(plugin, job, MapDetectResult(img=job.image, is_full_map=True))
    terrain = submitted.pop()
    assert terrain.stage == "terrain" and terrain.image is job.image
    _finish(plugin, terrain, MapDetectResult(img=job.image, earth_shifting=None))
    assert plugin._flag == MatchFlag.TRUE and submitted == []
    _finish(plugin, terrain, MapDetectResult(img=job.image, earth_shifting=4))
    pattern = submitted.pop()
    assert pattern.stage == "4" and pattern.image is job.image
    assert plugin._flag == MatchFlag.FALSE and overlay.map_pattern_matching
    images = [Image.new("RGBA", (10, 10)) for _ in range(3)]
    _finish(plugin, pattern, MapDetectResult(overlay_images=images))
    assert overlay.overlay_images == images and overlay.map_pattern_idx == 0
    assert overlay.crystal_layout_idx == 0 and not overlay.map_pattern_matching
    assert not plugin.ctx.services.require(MapRecognitionApi).ready()
    assert overlay.map_pattern_match_time > 0


def test_manual_visibility_survives_until_full_map_transition(maps, monkeypatch):
    plugin, _, _ = _ready(maps, monkeypatch)
    plugin._flag = MatchFlag.FALSE
    job = _job(plugin)
    _finish(plugin, job, MapDetectResult(img=job.image, is_full_map=True))
    plugin._toggle_overlay()
    assert not plugin._map_overlay_visible
    _finish(plugin, job, MapDetectResult(img=job.image, is_full_map=True))
    assert not plugin._map_overlay_visible
    _finish(plugin, job, MapDetectResult(img=job.image, is_full_map=False))
    _finish(plugin, job, MapDetectResult(img=job.image, is_full_map=True))
    assert plugin._map_overlay_visible


def test_day_one_interval_and_stale_results(maps, monkeypatch):
    plugin, fakes, submitted = _ready(maps, monkeypatch)
    plugin._flag = MatchFlag.FALSE
    fakes.events.publish(DayStarted(2))
    assert plugin._flag == MatchFlag.FALSE
    old = _job(plugin, "4")
    fakes.events.publish(DayStarted(1))
    assert plugin._flag == MatchFlag.PREPARE
    _finish(plugin, old, MapDetectResult(overlay_images=[Image.new("RGBA", (1, 1))]))
    assert plugin._overlay.overlay_images is None
    plugin._flag = MatchFlag.FALSE
    maps[3][0] += 2101
    job = _job(plugin)
    _finish(plugin, job, MapDetectResult(img=job.image, is_full_map=True))
    assert plugin._flag == MatchFlag.TRUE and submitted == []


def test_cycle_wraps_and_opacity_fades(maps, monkeypatch):
    plugin, _, _ = _ready(maps, monkeypatch)
    overlay = plugin._overlay
    overlay.set_overlay_images([Image.new("RGBA", (10, 10)) for _ in range(2)])
    plugin._set_overlay_visible(True)
    overlay._tick()
    plugin._cycle("last_overlay_image")
    assert overlay.map_pattern_idx == 1
    plugin._cycle("next_overlay_image")
    assert overlay.map_pattern_idx == 0
    overlay.crystal_layout_idx = 0
    plugin._cycle("last_crystal_layout")
    assert overlay.crystal_layout_idx == 4
    plugin._cycle("next_crystal_layout")
    assert overlay.crystal_layout_idx == 0
    plugin._set_overlay_visible(True)
    overlay._tick()
    assert overlay.isVisible()
    plugin._set_overlay_visible(False)
    for _ in range(10):
        overlay._tick()
    assert not overlay.isVisible() and overlay._real_opacity == 0


def test_calibration_square_cancel_and_reset(maps, monkeypatch):
    plugin, fakes, _ = _ready(maps, monkeypatch)
    fakes.region.regions[_REGION] = QRect(3, 4, 100, 80)
    plugin._calibrate_region()
    assert fakes.region.region(_REGION) == QRect(3, 4, 80, 80)
    plugin._flag = MatchFlag.FALSE
    plugin._overlay.map_pattern_matching = True
    monkeypatch.setattr(fakes.region, "request_region", lambda *args, **kwargs: None)
    plugin._calibrate_region()
    assert plugin._flag == MatchFlag.PREPARE and not plugin._overlay.map_pattern_matching
    plugin.config.return_topk.set(10)
    plugin.reset_settings()
    assert plugin.config.return_topk.value == 5 and fakes.region.region(_REGION) is None


def test_worker_drops_busy_frames_and_queued_results_after_deactivation(maps, monkeypatch):
    plugin, fakes, _, _ = maps
    plugin.on_activate()
    fakes.region.regions[_REGION] = QRect(0, 0, 100, 100)
    started, release = Event(), Event()
    calls = []

    def run(job):
        calls.append(job)
        started.set()
        assert release.wait(5)
        return MapDetectResult(img=job.image, is_full_map=False)

    monkeypatch.setattr(plugin, "_run_job", run)
    frame = FrameCaptured(solid_image(100, 100, (0, 0, 0)), 1.0)
    plugin._on_frame(frame)
    assert started.wait(5)
    plugin._on_frame(frame)
    assert len(calls) == 1 and plugin._busy
    release.set()
    process_events()
    assert not plugin._busy and plugin._flag == MatchFlag.TRUE
    # A completion queued by the previous activation cannot alter a new activation.
    old = calls[0]
    plugin.on_deactivate()
    plugin.ctx.release()
    plugin.on_activate()
    new = _job(plugin)
    plugin._pending_job, plugin._busy = new, True
    plugin._on_completed(old, MapDetectResult(), None)
    assert plugin._pending_job is new and plugin._busy


def test_day_timer_start_refresh_rewind_and_hud_readiness(maps):
    from nightreign_overlay.plugins.day_timer import plugin as day_module
    from nightreign_overlay.plugins.day_timer.plugin import DayTimerPlugin

    plugin, fakes, _, clock = maps
    plugin.on_activate()
    day = DayTimerPlugin(fakes.context("day_timer", Path(day_module.__file__).parent))
    day.on_load()
    day.on_activate()
    try:
        day._start_day(1)
        assert plugin._flag == MatchFlag.PREPARE
        assert "地图识别就绪" in day._label.text()
        plugin._flag = MatchFlag.FALSE
        day._detected_day(1)  # Repeated DAY I banner also refreshes map readiness.
        assert plugin._flag == MatchFlag.PREPARE
        plugin._flag = MatchFlag.FALSE
        clock[0] += 300
        day._update_timer()
        day._shift(300, "rewound", "test")
        assert plugin._flag == MatchFlag.FALSE
        assert "地图识别就绪" not in day._label.text()
    finally:
        day.on_deactivate()
        day.ctx.release()


@pytest.mark.parametrize(
    "action", ["previous_result", "next_result", "previous_crystal", "next_crystal", "recognize"]
)
@pytest.mark.parametrize("hidden_by", ["manual", "foreground"])
def test_map_hotkeys_only_respond_when_overlay_is_displayed(maps, monkeypatch, action, hidden_by):
    plugin, fakes, _ = _ready(maps, monkeypatch)
    overlay = plugin._overlay
    overlay.set_overlay_images([Image.new("RGBA", (10, 10)) for _ in range(2)])
    overlay.crystal_layout_idx = 0
    plugin._flag = MatchFlag.FALSE
    plugin._set_overlay_visible(True)
    overlay._tick()
    assert overlay.isVisible()
    hotkeys = fakes.services.require(HotkeyApi)
    hotkeys.set_binding(f"map_detect.{action}", HotkeyBinding(InputDevice.KEYBOARD, ("f8",)))

    def state():
        return (overlay.map_pattern_idx, overlay.crystal_layout_idx, plugin._flag, plugin._generation)

    def press():
        hotkeys.trigger_for_test(InputDevice.KEYBOARD, ("f8",))
        hotkeys.trigger_for_test(InputDevice.KEYBOARD, ())

    before = state()
    if hidden_by == "manual":
        plugin._set_overlay_visible(False)
        # Ignore shortcuts immediately, including while the window is still fading out.
        assert overlay.isVisible()
    else:
        manager = maps[2]
        manager._app_config.only_when_game_foreground.set(True)
        overlay.update_visibility()
        assert not overlay.isVisible()
    press()
    assert state() == before
    if hidden_by == "manual":
        for _ in range(10):
            overlay._tick()
        assert not overlay.isVisible()
        press()
        assert state() == before
        plugin._set_overlay_visible(True)
    else:
        manager._app_config.only_when_game_foreground.set(False)
    overlay._tick()
    assert overlay.isVisible()
    press()
    assert state() != before
