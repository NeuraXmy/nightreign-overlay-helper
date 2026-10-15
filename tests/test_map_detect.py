"""Map orchestration tests; actual screen recognition still needs game captures."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import numpy as np
import pytest
from PIL import Image
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QWidget

from conftest import process_events
from feature_fakes import FeatureServices, solid_image
from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.game_window import GameWindowMonitor
from nightreign_overlay.core.input import InputDevice
from nightreign_overlay.plugins.capture.api import FrameCaptured
from nightreign_overlay.plugins.day_timer.api import DayStarted
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.plugins.map_detect import detector as detector_module
from nightreign_overlay.plugins.map_detect import plugin as module
from nightreign_overlay.plugins.map_detect.api import MapRecognitionApi
from nightreign_overlay.plugins.map_detect.detector import MapDetectResult
from nightreign_overlay.plugins.map_detect.manual_catalog import PoiChoice
from nightreign_overlay.plugins.map_detect.plugin import MapDetectPlugin, MatchFlag, _Job
from nightreign_overlay.ui.components import ConfigChoiceCard, ConfigDoubleSpinCard, HotkeySettingCard
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
    algorithm = panel.findChildren(ConfigChoiceCard)[0]
    assert algorithm.item.key == "earth_shifting_algorithm"
    assert algorithm.comboBox.currentData() == "ncc"
    algorithm.comboBox.setCurrentIndex(1)
    assert plugin.config.snapshot().earth_shifting_algorithm == "template"
    plugin.config.earth_shifting_algorithm.reset()
    assert algorithm.comboBox.currentData() == "ncc"
    advanced = {card.item.key: card for card in panel.findChildren(ConfigDoubleSpinCard)}
    assert set(advanced) == {
        "full_map_error_threshold",
        "earth_shifting_ncc_threshold",
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
    hotkey_cards = {card._action_id: card for card in panel.findChildren(HotkeySettingCard)}
    assert "map_detect.manual_filter" in hotkey_cards
    plugin.on_activate()
    overlay = plugin._overlay
    assert overlay is not None and len(overlay.crystal_layout_imgs) == 5
    assert not overlay.isVisible()
    assert manager.windows() == [overlay, plugin._manual_overlay, plugin._controls]
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


def test_controls_clicks_share_shortcuts_without_showing_main_window(maps, monkeypatch):
    plugin, _, _ = _ready(maps, monkeypatch)
    overlay, controls = plugin._overlay, plugin._controls
    main = QWidget()
    requested = QSignalSpy(overlay.manager.mainWindowRequested)
    restored = QSignalSpy(overlay.manager.mainWindowShowRequested)
    overlay.manager.mainWindowRequested.connect(main.show)
    overlay.manager.mainWindowShowRequested.connect(main.show)
    overlay.set_overlay_images([Image.new("RGBA", (10, 10)) for _ in range(3)])
    overlay.crystal_layout_idx = 0
    plugin._set_overlay_visible(True)
    overlay._tick()
    controls.sync_from_map()
    assert controls.isVisible()
    assert overlay.config.input_mode.value == "passthrough"
    assert controls.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert not controls.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert controls.next_candidate.text() == "" and not controls.next_candidate.icon().isNull()
    QTest.mouseClick(controls.previous_candidate, Qt.MouseButton.LeftButton)
    controls.sync_from_map()
    assert overlay.map_pattern_idx == 2 and controls.candidate_index.text() == "#3/3"
    QTest.mouseClick(controls.next_candidate, Qt.MouseButton.LeftButton)
    assert overlay.map_pattern_idx == 0
    QTest.mouseClick(controls.previous_crystal, Qt.MouseButton.LeftButton)
    assert overlay.crystal_layout_idx == 4
    QTest.mouseClick(controls.next_crystal, Qt.MouseButton.LeftButton)
    assert overlay.crystal_layout_idx == 0
    plugin._flag = MatchFlag.FALSE
    generation = plugin._generation
    QTest.mouseClick(controls.recognize, Qt.MouseButton.LeftButton)
    assert plugin._flag == MatchFlag.PREPARE and plugin._generation == generation + 1
    assert not main.isVisible() and len(requested) == len(restored) == 0


def test_manual_filter_mode_hides_map_blocks_detection_and_toggles_from_controls(maps, monkeypatch):
    plugin, fakes, submitted = _ready(maps, monkeypatch)
    overlay, manual, controls = plugin._overlay, plugin._manual_overlay, plugin._controls
    plugin._set_overlay_visible(True)
    plugin._current_is_full_map = True
    overlay._tick()
    assert overlay.isVisible() and not manual.isVisible()

    generation = plugin._generation
    QTest.mouseClick(controls.manual_filter, Qt.MouseButton.LeftButton)
    assert plugin._manual_filtering and plugin._generation == generation + 1
    assert manual.isVisible() and not overlay.isVisible() and controls.isVisible()
    assert manual.pos() == overlay.pos() and manual.size() == overlay.size()
    assert not manual.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert controls.manual_filter.text() == "退出筛选"
    assert controls.candidate_group.isHidden() and controls.crystal_group.isHidden()
    assert not controls.recognize.isEnabled()
    assert manual.status_label.text() == "请选择特殊地形"
    assert "#ff4242" in manual.status_label.styleSheet()
    assert manual.layout().contentsMargins().top() == 10
    assert manual.layout().contentsMargins().left() == 10
    assert "rgba(53, 69, 87, 235)" in manual.earth_shifting_combo.styleSheet()
    assert not fakes.services.require(MapRecognitionApi).ready()

    frame = FrameCaptured(solid_image(100, 100, (0, 0, 0)), 1.0)
    plugin._on_frame(frame)
    assert [job.stage for job in submitted] == ["check"]
    blocked_generation = plugin._generation
    fakes.events.publish(DayStarted(1))
    assert plugin._generation == blocked_generation

    labels = [manual.earth_shifting_combo.itemText(index) for index in range(6)]
    assert labels == ["无地形", "雪山", "火山", "腐败森林", "大空洞", "隐城"]
    assert manual.nightlord_combo.itemText(0) == "所有"
    assert [manual.nightlord_combo.itemText(index) for index in range(1, 11)] == [
        "三头野兽",
        "碎身巨鳄",
        "慧心虫",
        "征兆",
        "平衡律法的魔物",
        "暗中飞驰的猎人",
        "雾中裂缝",
        "黑夜化形者",
        "安定者们",
        "废弃物之王",
    ]
    changed = QSignalSpy(manual.earthShiftingChanged)
    manual.earth_shifting_combo.setCurrentIndex(4)
    assert manual.earth_shifting == 4 and len(changed) == 1
    expected_candidates = len(plugin._manual_catalog.candidates(4, None, {}))
    assert manual.status_label.text() == f"剩余候选地图数量：{expected_candidates}"
    assert "color: white" in manual.status_label.styleSheet()
    visible_position = next(button for button in manual.position_buttons.values() if not button.isHidden())
    visible_position.click()
    assert manual._popup is not None and manual._popup.isVisible()
    manual.close_popup()
    boss_changed = QSignalSpy(manual.nightlordChanged)
    manual.nightlord_combo.setCurrentIndex(3)
    assert manual.nightlord == 2 and len(boss_changed) == 1

    manual.set_map_open(False)
    assert not manual.isVisible() and not controls.isVisible()
    assert manual.earth_shifting == 4 and manual.nightlord == 2
    manual.set_map_open(True)
    assert manual.isVisible() and controls.isVisible()
    assert manual.earth_shifting == 4 and manual.nightlord == 2

    QTest.mouseClick(controls.manual_filter, Qt.MouseButton.LeftButton)
    assert not plugin._manual_filtering
    assert not manual.isVisible() and overlay.isVisible() and controls.isVisible()
    assert controls.manual_filter.text() == "手动筛选"
    assert controls.recognize.isEnabled()

    QTest.mouseClick(controls.manual_filter, Qt.MouseButton.LeftButton)
    assert manual.earth_shifting_combo.currentIndex() == -1
    assert manual.earth_shifting is None
    assert manual.nightlord_combo.currentIndex() == 0
    assert manual.nightlord is None


def test_manual_filter_hotkey_is_a_toggle_and_requires_a_region(maps, monkeypatch):
    plugin, fakes, _ = _ready(maps, monkeypatch)
    hotkeys = fakes.services.require(HotkeyApi)
    hotkeys.set_binding("map_detect.manual_filter", HotkeyBinding(InputDevice.KEYBOARD, ("f9",)))

    def press():
        hotkeys.trigger_for_test(InputDevice.KEYBOARD, ("f9",))
        hotkeys.trigger_for_test(InputDevice.KEYBOARD, ())

    press()
    assert plugin._manual_filtering
    press()
    assert not plugin._manual_filtering
    fakes.region.regions.pop(_REGION)
    press()
    assert not plugin._manual_filtering


def test_manual_poi_constraints_converge_or_reset_without_losing_filters(maps, monkeypatch):
    plugin, _, submitted = _ready(maps, monkeypatch)
    plugin._current_is_full_map = True
    plugin._toggle_manual_filter()
    manual = plugin._manual_overlay
    catalog = plugin._manual_catalog
    assert all(button.isHidden() for button in manual.position_buttons.values())
    manual.earth_shifting_combo.setCurrentIndex(0)
    manual.nightlord_combo.setCurrentIndex(1)
    assert manual.earth_shifting == 0 and manual.nightlord == 0

    badge_pos, badge_base = next(
        (pos, base)
        for pos in catalog.positions(0, 0)
        for base in catalog.base_options(0, 0, {}, pos)
        if base and any(value is not None for value in catalog.subicon_options(0, 0, {}, pos, base))
    )
    manual.set_filter_state({badge_pos: PoiChoice(badge_base)}, {})
    assert not manual.badge_buttons[badge_pos].isHidden()
    manual.badge_buttons[badge_pos].click()
    assert manual._popup is not None and manual._popup.isVisible()
    manual.close_popup()

    target = catalog.candidates(0, 0, {})[0]
    explicit = {pos: PoiChoice(*catalog.value(target, pos)) for pos in catalog.positions(0, 0)}
    manual.set_filter_state(explicit, {})
    plugin._rematch_manual_filter()
    assert not plugin._manual_filtering
    assert submitted[-1].stage == "draw" and submitted[-1].pattern_ids == (target.id,)

    # Re-entering starts clean; an impossible setting resets only strongholds and shows the warning.
    plugin._toggle_manual_filter()
    manual.earth_shifting_combo.setCurrentIndex(0)
    manual.nightlord_combo.setCurrentIndex(1)
    pos = catalog.positions(0, 0)[0]
    impossible_base = next(
        base for base in catalog.groups() if base not in catalog.base_options(0, 0, {}, pos)
    )
    revision = plugin._manual_revision
    plugin._on_manual_poi_choice(pos, PoiChoice(impossible_base))
    assert plugin._manual_filtering and not manual.explicit_choices
    assert manual.status_label.isVisible()
    assert manual.status_label.text() == "筛选为空，请重新设置"
    assert "#ff4242" in manual.status_label.styleSheet()
    assert manual.earth_shifting == 0 and manual.nightlord == 0
    assert plugin._manual_revision == revision + 1


def test_manual_apply_now_draws_up_to_five_candidates_sorted_by_id(maps, monkeypatch):
    plugin, _, submitted = _ready(maps, monkeypatch)
    plugin._current_is_full_map = True
    plugin._toggle_manual_filter()
    manual = plugin._manual_overlay
    catalog = plugin._manual_catalog
    manual.earth_shifting_combo.setCurrentIndex(0)
    assert manual.status_label.isVisible() and manual.apply_button.isHidden()

    # Narrow with real stronghold values until 2..5 candidates remain.
    explicit, candidates = None, []
    for target in catalog.candidates(0, None, {}):
        constraints = {}
        for pos in catalog.positions(0, None):
            constraints[pos] = PoiChoice(*catalog.value(target, pos))
            candidates = catalog.candidates(0, None, constraints)
            if len(candidates) <= 5:
                break
        if 2 <= len(candidates) <= 5:
            explicit = constraints
            break
    assert explicit is not None

    manual.set_filter_state(explicit, {})
    plugin._rematch_manual_filter()
    assert plugin._manual_filtering
    assert manual.status_label.text() == f"剩余候选地图数量：{len(candidates)}"
    assert not manual.apply_button.isHidden()
    assert manual.apply_button.geometry().right() < manual.status_label.geometry().left()

    manual.apply_button.click()
    assert not plugin._manual_filtering
    job = submitted[-1]
    assert job.stage == "draw" and job.earth_shifting == 0 and job.nightlord is None
    assert job.pattern_ids == tuple(sorted(pattern.id for pattern in candidates))

    drawn = []
    monkeypatch.setattr(
        detector_module.MapDetector,
        "_draw_overlay_image",
        lambda _self, match, _size, index: drawn.append((match.pattern.id, index)) or index,
    )
    result = plugin._run_job(job)
    assert [pattern.id for pattern in result.patterns] == list(job.pattern_ids)
    assert drawn == [(pattern_id, index) for index, pattern_id in enumerate(job.pattern_ids)]
    assert result.overlay_images == list(range(len(job.pattern_ids)))


def test_manual_single_poi_auto_recognition_submits_and_applies_choice(maps, monkeypatch):
    plugin, fakes, submitted = _ready(maps, monkeypatch)
    plugin._current_is_full_map = True
    plugin._toggle_manual_filter()
    manual = plugin._manual_overlay
    catalog = plugin._manual_catalog
    manual.earth_shifting_combo.setCurrentIndex(0)
    manual.nightlord_combo.setCurrentIndex(1)
    pos = catalog.positions(0, 0)[0]
    ctype = next(ctype for ctype in catalog.info.possible_poi_types[(0, 0, pos)] if ctype != 0)
    fakes.capture.frame = FrameCaptured(solid_image(100, 100, (20, 30, 40)), 1.0, hdr=True)
    monkeypatch.setattr(module.QTimer, "singleShot", lambda _delay, callback: callback())

    plugin._request_manual_auto_recognition(pos)
    assert fakes.capture.captures == 1
    assert not manual._capture_hidden
    poi_job = submitted[-1]
    assert poi_job.stage == "poi" and poi_job.poi_position == pos
    assert poi_job.earth_shifting == 0 and poi_job.nightlord == 0 and poi_job.hdr

    _finish(plugin, poi_job, MapDetectResult(poi_types={pos: ctype}))
    assert manual.explicit_choices[pos] == catalog.choice_from_ctype(ctype)
    assert not plugin._manual_auto_in_flight


def test_controls_follow_geometry_scale_fade_and_hidden_state(maps, monkeypatch):
    plugin, _, _ = _ready(maps, monkeypatch)
    overlay, controls = plugin._overlay, plugin._controls
    plugin._region = QRect(30, 40, 750, 750)
    plugin._set_overlay_visible(True)
    overlay._tick()
    controls.sync_from_map()
    height = controls.height()
    assert controls.x() == overlay.frameGeometry().left()
    assert controls.y() == overlay.frameGeometry().bottom() + 1
    assert controls.width() == overlay.width()
    assert controls.windowOpacity() == pytest.approx(overlay.windowOpacity())
    overlay.config.scale.set(150)
    controls.sync_from_map()
    assert controls.height() == round(height * 1.5)
    assert controls.width() == overlay.width()
    assert controls.y() == overlay.frameGeometry().bottom() + 1
    plugin._set_overlay_visible(False)
    for _ in range(10):
        overlay._tick()
        controls.sync_from_map()
        assert controls.isVisible() == overlay.isVisible()
        assert controls.windowOpacity() == pytest.approx(overlay.windowOpacity())
    assert not controls.isVisible()


@pytest.mark.parametrize("scale", [50, 100, 150, 200])
def test_controls_scale_every_dimension_proportionally(maps, monkeypatch, scale):
    plugin, _, _ = _ready(maps, monkeypatch)
    overlay, controls = plugin._overlay, plugin._controls
    plugin._region = QRect(0, 0, 750, 750)
    plugin._set_overlay_visible(True)
    overlay.config.scale.set(scale)
    controls.sync_from_map()
    factor = scale / 100
    assert controls.width() == round(750 * factor)
    assert controls.height() == round(45 * factor)
    assert controls.recognize.height() == round(29 * factor)
    assert controls.previous_candidate.size().width() == round(36 * factor)
    assert controls.candidate_index.height() == round(29 * factor)
    assert controls.previous_candidate.iconSize().height() == round(16 * factor)
    assert controls.row.spacing() == round(8 * factor)


def test_controls_crystals_only_when_applicable_and_no_results_disable_cycling(maps, monkeypatch):
    plugin, _, _ = _ready(maps, monkeypatch)
    overlay, controls = plugin._overlay, plugin._controls
    controls.sync_from_map()
    assert controls.crystal_group.isHidden()
    assert controls.candidate_index.text() == "#0/0"
    assert not controls.previous_candidate.isEnabled() and not controls.next_candidate.isEnabled()
    overlay.crystal_layout_idx = 1
    controls.sync_from_map()
    assert not controls.crystal_group.isHidden() and controls.crystal_index.text() == "#1/4"
    overlay.crystal_layout_idx = None
    controls.sync_from_map()
    assert controls.crystal_group.isHidden()


@pytest.mark.parametrize("scale", [50, 67, 85, 100, 115, 125, 150, 175, 200])
def test_controls_buttons_fit_inside_toolbar_and_groups(maps, monkeypatch, scale):
    plugin, _, _ = _ready(maps, monkeypatch)
    overlay, controls = plugin._overlay, plugin._controls
    plugin._region = QRect(0, 0, 750, 750)
    overlay.crystal_layout_idx = 1
    plugin._set_overlay_visible(True)
    overlay.config.scale.set(scale)
    overlay._tick()
    controls.sync_from_map()
    process_events(1)
    for button in controls._buttons:
        top = button.mapTo(controls, QPoint()).y()
        assert top >= 0
        assert top + button.height() <= controls.height(), (
            scale,
            button.geometry(),
            button.parentWidget().geometry(),
            top,
            controls.height(),
        )
        assert button.y() >= 0
        assert button.geometry().bottom() < button.parentWidget().height()


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
