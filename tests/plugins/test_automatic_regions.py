"""Automatic HUD geometry and manual overrides through the real region/feature services."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
import yaml
from PIL import Image
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QPixmap

from nightreign_overlay.core import i18n
from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.game_window import GameWindowMonitor
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.paths import resource_path
from nightreign_overlay.plugins.art_timer.plugin import ArtTimerPlugin
from nightreign_overlay.plugins.capture.api import FrameCaptured, crop_rgb
from nightreign_overlay.plugins.day_timer.plugin import DayTimerPlugin
from nightreign_overlay.plugins.hp_marker.plugin import HpMarkerPlugin
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding, InputDevice
from nightreign_overlay.plugins.map_detect.plugin import MapDetectPlugin, MatchFlag
from nightreign_overlay.plugins.rain_timer.plugin import RainTimerPlugin
from nightreign_overlay.plugins.region.api import RegionApi, RegionStatus
from nightreign_overlay.plugins.region.automatic import automatic_region
from nightreign_overlay.plugins.region.plugin import RegionPlugin
from nightreign_overlay.ui.overlay import OverlayManager
from tests.support.feature_fakes import FeatureServices, solid_image
from tests.support.paths import PROJECT_ROOT
from tests.support.platform import FakeBackend

_REGIONS = {
    "day_timer.detect_region": (1112, 733, 342, 95),
    "rain_timer.hp_region": (240, 58, 20, 8),
    "map_detect.map_region": (1454, 228, 990, 990),
    "hp_marker.hpbar_region": (223, 56, 112, 12),
    "art_timer.art_region": (1206, 1260, 143, 140),
}
_HD_REGIONS = {
    "day_timer.detect_region": (834, 550, 256, 71),
    "rain_timer.hp_region": (180, 44, 15, 6),
    "map_detect.map_region": (1090, 171, 742, 742),
    "hp_marker.hpbar_region": (167, 42, 84, 9),
    "art_timer.art_region": (904, 945, 107, 105),
}


@pytest.mark.parametrize("origin", [(0, 0), (-2560, -1440), (320, 180)])
@pytest.mark.parametrize("size,expected", [((2560, 1440), _REGIONS), ((1920, 1080), _HD_REGIONS)])
def test_default_regions_scale_once_in_physical_client_pixels(origin, size, expected):
    client = QRect(*origin, *size)
    for key, rect in expected.items():
        actual = automatic_region(key, client)
        assert actual == QRect(*rect).translated(*origin)
        assert client.contains(actual)


@pytest.mark.parametrize("size", [(640, 360), (1280, 720), (3840, 2160), (1921, 1080)])
def test_supported_sizes_keep_map_square(size):
    client = QRect(20, -40, *size)
    for key in _REGIONS:
        rect = automatic_region(key, client)
        assert rect is not None and client.contains(rect)
    rect = automatic_region("map_detect.map_region", client)
    assert rect.width() == rect.height()


@pytest.mark.parametrize(
    "client",
    [
        None,
        QRect(),
        QRect(0, 0, 320, 180),
        QRect(0, 0, 1920, 1200),
        QRect(0, 0, 3440, 1440),
        QRect(0, 0, 1080, 1920),
    ],
)
def test_unknown_layout_never_guesses_a_region(client):
    assert all(automatic_region(key, client) is None for key in _REGIONS)
    assert automatic_region("custom.region", QRect(0, 0, 2560, 1440)) is None


@pytest.fixture
def regions(store, tmp_path, monkeypatch):
    fakes = FeatureServices(store, tmp_path)
    fakes.services.unregister(RegionApi)
    window = [QRect(0, 0, 2560, 1440)]
    monkeypatch.setattr(fakes.capture, "game_client_rect", lambda: window[0])
    plugin = RegionPlugin(fakes.context("region", tmp_path))
    plugin.on_load()
    plugin.on_activate()
    api = fakes.services.require(RegionApi)
    yield plugin, api, fakes, window
    plugin.ctx.release()
    fakes.input.ctx.release()


def test_manual_overrides_are_per_region_and_only_manual_values_are_persisted(regions, store):
    plugin, api, _, window = regions
    for key, rect in _REGIONS.items():
        assert api.region(key) == QRect(*rect)
        assert api.region_source(key) == "automatic"
    assert plugin.config.regions.value == {}
    manual = QRect(-100, 35, 90, 70)
    api.save_region("day_timer.detect_region", manual)
    window[0] = QRect(100, -50, 1920, 1080)
    assert api.region("day_timer.detect_region") == manual
    assert api.region_source("day_timer.detect_region") == "manual"
    assert api.region("map_detect.map_region") == QRect(1190, 121, 742, 742)
    store.flush()
    data = yaml.safe_load(store.path.read_text(encoding="utf-8"))
    assert data["plugins"]["region"]["regions"] == {"day_timer.detect_region": [-100, 35, 90, 70]}
    reloaded = ConfigStore(store.path)
    try:
        assert (
            reloaded.bind(type(plugin.config), "plugins.region").regions.value == plugin.config.regions.value
        )
    finally:
        reloaded.deleteLater()
    window[0] = None
    assert api.region("day_timer.detect_region") == manual
    assert api.region("map_detect.map_region") is None
    api.clear_region("day_timer.detect_region")
    assert api.region("day_timer.detect_region") is None
    window[0] = QRect(0, 0, 2560, 1440)
    assert api.region("day_timer.detect_region") == QRect(*_REGIONS["day_timer.detect_region"])
    assert plugin.config.regions.value == {}


def test_window_resize_exit_and_capture_service_loss_do_not_reuse_stale_defaults(regions):
    _, api, fakes, window = regions
    key = "map_detect.map_region"
    for client in [
        QRect(-1920, 80, 1920, 1080),
        QRect(90, 40, 2560, 1440),
        None,
        QRect(0, 0, 3440, 1440),
        QRect(0, 0, 1280, 720),
    ]:
        window[0] = client
        assert api.region(key) == automatic_region(key, client)
    from nightreign_overlay.plugins.capture.api import CaptureApi

    fakes.services.unregister(CaptureApi)
    assert api.region(key) is None
    api.save_region(key, QRect(10, 20, 100, 100))
    assert api.region(key) == QRect(10, 20, 100, 100)


def test_canceled_calibration_preserves_automatic_or_manual_source(regions, monkeypatch):
    plugin, api, _, _ = regions
    key = "map_detect.map_region"
    monkeypatch.setattr(api, "_select", lambda *_a, **_k: None)
    assert api.request_region(key) is None
    assert api.region_source(key) == "automatic" and plugin.config.regions.value == {}
    api.save_region(key, QRect(10, 20, 100, 100))
    assert api.request_region(key) is None
    assert api.region_source(key) == "manual" and api.region(key) == QRect(10, 20, 100, 100)


def test_status_shows_source_and_clears_only_the_selected_manual_region(regions, monkeypatch):
    plugin, api, fakes, window = regions
    translator = Translator("zh_CN")
    translator.load_dir(i18n.CORE_NAMESPACE, resource_path("i18n"))
    monkeypatch.setattr(i18n, "_translator", translator)
    status = RegionStatus(fakes.services, "map_detect.map_region")
    status.show()
    try:
        assert status.label.text() == "自动（16:9）" and status.clearButton.isHidden()
        assert status.calibrated and status._refresh_timer.isActive()
        api.save_region("map_detect.map_region", QRect(0, 0, 100, 100))
        api.save_region("day_timer.detect_region", QRect(20, 30, 40, 50))
        status.refresh()
        assert status.label.text() == "已标定" and not status.clearButton.isHidden()
        status.clearButton.click()
        assert status.label.text() == "自动（16:9）"
        assert set(plugin.config.regions.value) == {"day_timer.detect_region"}
        window[0] = None
        status.refresh()
        assert status.label.text() == "等待自动区域" and not status.calibrated
    finally:
        status.hide()
        assert not status._refresh_timer.isActive()
        status.deleteLater()


def _feature(plugin_class, fakes, store):
    backend = FakeBackend()
    manager = OverlayManager(backend, store.bind(AppConfig, "app"), GameWindowMonitor(backend, fakes.events))
    fakes.services.register(OverlayManager, manager)
    root = PROJECT_ROOT / "src/nightreign_overlay/plugins" / plugin_class.manifest.id
    plugin = plugin_class(fakes.context(plugin_class.manifest.id, root))
    plugin.on_load()
    plugin.on_activate()
    return plugin, manager


def _press(fakes, action, key="f8"):
    hotkeys = fakes.services.require(HotkeyApi)
    hotkeys.set_binding(action, HotkeyBinding(InputDevice.KEYBOARD, (key,)))
    hotkeys.trigger_for_test(InputDevice.KEYBOARD, (key,))
    hotkeys.trigger_for_test(InputDevice.KEYBOARD, ())


@pytest.mark.parametrize(
    "cls,key",
    [
        (DayTimerPlugin, "day_timer.detect_region"),
        (RainTimerPlugin, "rain_timer.hp_region"),
        (ArtTimerPlugin, "art_timer.art_region"),
        (HpMarkerPlugin, "hp_marker.hpbar_region"),
        (MapDetectPlugin, "map_detect.map_region"),
    ],
)
def test_calibration_hotkeys_work_with_automatic_defaults(regions, store, monkeypatch, cls, key):
    region_plugin, api, fakes, _ = regions
    plugin, _ = _feature(cls, fakes, store)
    selected = QRect(10, 20, 100, 100)
    dialog = SimpleNamespace(_pixmap=QPixmap.fromImage(solid_image(128, 128, (1, 2, 3))))
    monkeypatch.setattr(api, "_select", lambda *_a, **_k: ({0: selected}, dialog))
    try:
        assert api.region_source(key) == "automatic"
        _press(fakes, f"{plugin.id}.calibrate_region")
        assert api.region_source(key) == "manual" and api.region(key) == selected
        assert set(region_plugin.config.regions.value) == {key}
        assert not plugin._calibrating
    finally:
        plugin.on_deactivate()
        plugin.ctx.release()


def test_map_auto_area_drives_capture_reidentify_and_rejects_moved_window_result(regions, store, monkeypatch):
    _, api, fakes, window = regions
    plugin, _ = _feature(MapDetectPlugin, fakes, store)
    submitted = []
    monkeypatch.setattr(plugin, "_submit", submitted.append)
    try:
        window[0] = QRect(-1920, 80, 1920, 1080)
        frame = solid_image(1920, 1080, (12, 34, 56))
        frame.setOffset(QPoint(-1920, 80))
        plugin._on_frame(FrameCaptured(frame, 1000.0))
        job = submitted[-1]
        assert job.region == (-830, 251, 742, 742)
        assert job.image.shape == (742, 742, 3) and (job.image == [12, 34, 56]).all()
        assert crop_rgb(frame, api.region("map_detect.map_region")).shape == (742, 742, 3)
        plugin._overlay.set_overlay_images([Image.new("RGBA", (10, 10))])
        plugin._set_overlay_visible(True)
        plugin._overlay._tick()
        assert plugin._overlay.isVisible()
        plugin._flag = MatchFlag.FALSE
        generation = plugin._generation
        _press(fakes, "map_detect.recognize")
        assert plugin._flag == MatchFlag.PREPARE and plugin._generation > generation
        # Resizing/moving invalidates a queued result just as changing a manual area does.
        job = replace(job, generation=plugin._generation)
        plugin._pending_job = job
        plugin._busy = True
        window[0] = QRect(0, 0, 2560, 1440)
        plugin._on_completed(job, None, None)
        assert not plugin._busy and plugin._flag == MatchFlag.PREPARE
        assert plugin._generation > job.generation
    finally:
        plugin.on_deactivate()
        plugin.ctx.release()


def test_art_hotkey_can_request_first_frame_before_any_stream_exists(regions, store):
    _, api, fakes, _ = regions
    plugin, _ = _feature(ArtTimerPlugin, fakes, store)
    try:
        assert fakes.capture.streams == set() and fakes.capture.latest_frame() is None
        _press(fakes, "art_timer.use_art")
        assert plugin._detect_timer.isActive()
        plugin._detect_timer.stop()
        plugin._detect_art()
        assert fakes.capture.captures == 1
        assert api.region_source("art_timer.art_region") == "automatic"
    finally:
        plugin.on_deactivate()
        plugin.ctx.release()
