"""HP marker lifecycle, structural detection, geometry and asynchronous frame handling."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import numpy as np
import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtWidgets import QWidget

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.game_window import GameWindowMonitor
from nightreign_overlay.core.screens import ScreenMapping
from nightreign_overlay.plugins.capture.api import FrameCaptured
from nightreign_overlay.plugins.hp_marker import plugin as module
from nightreign_overlay.plugins.hp_marker.plugin import HpMarkerPlugin, _Job
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.ui.components import ConfigDoubleSpinCard, ConfigRangeCard
from nightreign_overlay.ui.overlay import OverlayManager
from tests.support.feature_fakes import FeatureServices, solid_image
from tests.support.platform import FakeBackend
from tests.support.qt import process_events


@pytest.fixture
def hp(store, tmp_path):
    fakes = FeatureServices(store, tmp_path)
    backend = FakeBackend()
    app = store.bind(AppConfig, "app")
    monitor = GameWindowMonitor(backend, fakes.events)
    manager = OverlayManager(backend, app, monitor)
    fakes.services.register(OverlayManager, manager)
    plugin = HpMarkerPlugin(fakes.context("hp_marker", Path(module.__file__).parent))
    plugin.on_load()
    yield plugin, fakes, manager, app, monitor, backend
    plugin.on_deactivate()
    plugin.ctx.release()
    fakes.input.ctx.release()
    monitor.stop()


def _finish(plugin, region, length, *, generation=None):
    job = _Job(
        plugin._generation if generation is None else generation,
        region,
        np.zeros((15, 100, 3), np.uint8),
        plugin.config.snapshot(),
    )
    plugin._pending = job
    plugin._on_completed(job, length, None)


def test_lifecycle_settings_and_shortcut(hp):
    plugin, fakes, manager, *_ = hp
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)
    cards = {card.item.key: card for card in panel.findChildren(ConfigDoubleSpinCard)}
    cards["hpbar_low_hp_marker"].spinBox.setValue(0.35)
    assert plugin.config.hpbar_low_hp_marker.value == 0.35
    plugin.on_activate()
    overlay = plugin._overlay
    assert not overlay.isVisible()
    assert manager.windows() == [overlay]
    assert fakes.capture.streams == {"hp_marker"}
    assert fakes.input.ctx.services is plugin.ctx.services
    assert fakes.services.require(HotkeyApi).binding(module._CALIBRATE, HotkeyBinding(None)) == HotkeyBinding(
        None
    )
    plugin.on_deactivate()
    plugin.ctx.release()
    assert manager.windows() == []
    assert not overlay._timer.isActive() and fakes.capture.streams == set()


def test_marker_positions_and_failure_preserves_display(hp):
    plugin, fakes, _, app, *_ = hp
    region = QRect(10, 20, 15, 15)
    fakes.region.regions[module._REGION_KEY] = region
    plugin.on_activate()
    _finish(plugin, region, 500)
    overlay = plugin._overlay
    assert overlay.isVisible()
    assert overlay.geometry() == QRect(10, 13, 500, 7)
    assert [line.geometry() for line in overlay.lines] == [
        QRect(199, 0, 3, 7),
        QRect(424, 0, 3, 7),
        QRect(497, 0, 3, 7),
    ]
    _finish(plugin, region, None)
    assert overlay.isVisible() and overlay.width() == 500
    assert overlay.config.position.value is None
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    app.overlay_mode.set("window")
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    _finish(plugin, region, 0)
    assert not overlay.isVisible()


def test_foreground_gate_and_appearance_updates(hp):
    plugin, fakes, _, app, monitor, backend = hp
    region = QRect(10, 20, 15, 15)
    fakes.region.regions[module._REGION_KEY] = region
    plugin.on_activate()
    _finish(plugin, region, 500)
    app.only_when_game_foreground.set(True)
    monitor.start()
    assert not plugin._overlay.isVisible()
    backend.title = "ELDEN RING NIGHTREIGN"
    monitor._poll()
    assert plugin._overlay.isVisible()
    plugin.config.hpbar_low_hp_marker.set(0.2)
    plugin.config.line_width.set(5)
    plugin.config.line_height.set(9)
    plugin.config.marker_size.set(200)
    plugin.config.marker_color.set("#ff0000")
    plugin._overlay._tick()
    assert plugin._overlay.lines[0].geometry() == QRect(95, 0, 10, 18)
    assert plugin._overlay.lines[0].color.name() == "#ff0000"
    assert plugin._overlay.y() == 2


def test_worker_expands_width_keeps_raw_pixels_and_drops_busy_frames(hp, monkeypatch):
    plugin, fakes, *_ = hp
    region = QRect(10, 20, 5, 15)
    fakes.region.regions[module._REGION_KEY] = region
    started, release = Event(), Event()
    calls = []

    def run(job):
        calls.append(job)
        started.set()
        assert release.wait(5)
        return 500

    monkeypatch.setattr(plugin, "_run_job", run)
    monkeypatch.setattr(
        module, "screen_mappings", lambda _: [ScreenMapping(QRect(0, 0, 2000, 100), 1, QPoint())]
    )
    plugin.on_activate()
    frame = FrameCaptured(solid_image(2000, 100, (32, 64, 128)), 0, hdr=True)
    plugin._on_frame(frame)
    try:
        assert started.wait(5)
        plugin._on_frame(frame)
        assert len(calls) == 1
        assert calls[0].image.shape == (45, 1875, 3)
        assert calls[0].region == region
        assert calls[0].capture_region == QRect(10, 5, 1875, 45)
        assert tuple(calls[0].image[0, 0]) == (32, 64, 128)
        plugin._generation += 1
    finally:
        release.set()
    process_events()
    assert plugin._pending is None
    assert not plugin._overlay.isVisible()


def test_calibration_reset_and_missing_region(hp):
    plugin, fakes, *_ = hp
    region = QRect(10, 20, 15, 15)
    fakes.region.regions[module._REGION_KEY] = region
    plugin.on_activate()
    plugin._calibrate_region()
    assert fakes.region.requests[-1] == (
        module._REGION_KEY,
        plugin.ctx.tr("settings.region.annotate"),
        "#eb3b3b",
    )
    _finish(plugin, region, 500)
    plugin.config.hpbar_low_hp_marker.set(0.3)
    plugin.reset_settings()
    assert plugin.config.hpbar_low_hp_marker.value == 0.4
    assert fakes.region.region(module._REGION_KEY) is None
    assert not plugin._overlay.isVisible()
    plugin._on_frame(FrameCaptured(solid_image(100, 100, (0, 0, 0)), 0))
    assert plugin._pending is None


def test_stale_result_does_not_clear_new_activation_job(hp):
    plugin, fakes, *_ = hp
    region = QRect(10, 20, 15, 15)
    fakes.region.regions[module._REGION_KEY] = region
    plugin.on_activate()
    old = _Job(plugin._generation, region, np.zeros((15, 100, 3), np.uint8), plugin.config.snapshot())
    plugin.on_deactivate()
    plugin.ctx.release()
    plugin.on_activate()
    current = _Job(plugin._generation, region, old.image, plugin.config.snapshot())
    plugin._pending = current
    plugin._on_completed(old, 500, None)
    assert plugin._pending is current and not plugin._overlay.isVisible()
    plugin._on_completed(current, 500, None)
    assert plugin._pending is None and plugin._overlay.isVisible()


@pytest.mark.parametrize(
    "ratio,geometry,positions",
    [
        (1.0, QRect(10, 13, 503, 7), [200, 426, 500]),
        (1.25, QRect(8, 9, 402, 7), [159, 340, 399]),
        (1.5, QRect(6, 6, 335, 7), [133, 283, 332]),
        (2.0, QRect(5, 3, 251, 7), [99, 212, 248]),
    ],
)
def test_dpi_converts_bar_coordinates_but_preserves_logical_marker_size(
    hp, monkeypatch, ratio, geometry, positions
):
    from types import SimpleNamespace

    from nightreign_overlay.plugins.hp_marker import overlay as overlay_module

    plugin, fakes, *_ = hp
    region = QRect(10, 20, 15, 15)
    fakes.region.regions[module._REGION_KEY] = region
    plugin.on_activate()
    screen = SimpleNamespace(geometry=lambda: QRect(0, 0, 1920, 1080), devicePixelRatio=lambda: ratio)
    monkeypatch.setattr(overlay_module.QGuiApplication, "screens", lambda: [screen])
    monkeypatch.setattr(plugin._overlay, "devicePixelRatio", lambda: ratio)
    _finish(plugin, region, 503)
    assert plugin._overlay.geometry() == geometry
    assert [line.geometry() for line in plugin._overlay.lines] == [QRect(x, 0, 3, 7) for x in positions]
    plugin.config.marker_size.set(175)
    plugin._overlay._tick()
    assert all(line.size().width() == 5 and line.size().height() == 12 for line in plugin._overlay.lines)
    assert plugin._overlay.y() == geometry.y() - 5


def test_detection_offset_is_available_in_advanced_settings(hp):
    plugin, *_ = hp
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)
    cards = {card.item.key: card for card in panel.findChildren(ConfigRangeCard)}
    assert "hpbar_detection_offset" in cards
    assert plugin.config.snapshot().hpbar_detection_offset == 3
    cards["hpbar_detection_offset"].slider.setValue(7)
    assert plugin.config.snapshot().hpbar_detection_offset == 7
