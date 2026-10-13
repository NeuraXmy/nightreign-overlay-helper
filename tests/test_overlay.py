"""Overlay window behaviour and the overlay_test plugin running against the real core services."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QApplication, QWidget

from conftest import process_events
from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.game_window import GameForegroundChanged, GameWindowMonitor
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.platforms import PlatformBackend
from nightreign_overlay.plugin import PluginManager, PluginState
from nightreign_overlay.plugins.day_timer.plugin import _DayTimerHud
from nightreign_overlay.plugins.hud.config import HudConfig
from nightreign_overlay.plugins.hud.overlay import HudOverlay
from nightreign_overlay.plugins.overlay_test.api import OverlayTestApi
from nightreign_overlay.plugins.overlay_test.overlay import OverlayTestWindow
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayManager, OverlayWindow


class FakeBackend(PlatformBackend):
    name = "fake"
    supports_foreground_detection = True
    supports_transparent_overlay = True

    def __init__(self) -> None:
        self.title: str | None = None

    def foreground_window_title(self) -> str | None:
        return self.title


@dataclass
class Core:
    backend: FakeBackend
    config: AppConfig
    events: EventBus
    services: ServiceRegistry
    monitor: GameWindowMonitor
    overlays: OverlayManager


@pytest.fixture
def core(store: ConfigStore, qapp: QApplication) -> Iterator[Core]:
    backend = FakeBackend()
    config = store.bind(AppConfig, "app")
    events = EventBus()
    services = ServiceRegistry()
    monitor = GameWindowMonitor(backend, events, window_title="NIGHTREIGN")
    overlays = OverlayManager(backend, config, monitor)
    for api, impl in (
        (PlatformBackend, backend),
        (AppConfig, config),
        (GameWindowMonitor, monitor),
        (OverlayManager, overlays),
    ):
        services.register(api, impl)
    yield Core(backend, config, events, services, monitor, overlays)
    for window in overlays.windows():
        window.dispose()


@pytest.fixture
def window(core: Core, store: ConfigStore) -> OverlayWindow:
    overlay = OverlayWindow(core.overlays, store.bind(OverlayConfig, "overlay"), "test", QSize(200, 100))
    overlay.show_overlay()
    return overlay


def test_scale_resizes_window(window: OverlayWindow) -> None:
    assert window.size() == QSize(200, 100)
    window.config.scale.set(150)
    assert window.size() == QSize(300, 150)


def test_opacity(window: OverlayWindow) -> None:
    window.config.opacity.set(40)
    assert window.windowOpacity() == pytest.approx(0.4, abs=0.01)


def test_window_mode_switch(core: Core, window: OverlayWindow) -> None:
    assert core.overlays.transparent_mode
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    core.config.overlay_mode.set("window")
    assert not core.overlays.transparent_mode
    assert not window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.isVisible()
    core.backend.supports_transparent_overlay = False
    core.config.overlay_mode.set("auto")
    assert core.overlays.transparent_mode
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint


def test_hud_disable_hides_its_window(core: Core, store: ConfigStore) -> None:
    config = store.bind(HudConfig, "plugins.hud")
    overlay = HudOverlay(core.overlays, store.bind(OverlayConfig, "hud.overlay"), config, "HUD")
    overlay.add_widget("test", QWidget(), order=0)
    assert overlay.isVisible()

    config.enabled.set(False)
    assert not overlay.isVisible()

    config.enabled.set(True)
    assert overlay.isVisible()


def test_input_modes_apply_transparent_passthrough_only_in_overlay_mode(
    core: Core, window: OverlayWindow
) -> None:
    window.config.input_mode.set("locked")
    assert not window.windowFlags() & Qt.WindowType.WindowTransparentForInput

    window.config.input_mode.set("passthrough")
    assert window.windowFlags() & Qt.WindowType.WindowTransparentForInput
    core.config.overlay_mode.set("window")
    assert not window.windowFlags() & Qt.WindowType.WindowTransparentForInput


def test_follows_game_foreground(core: Core, window: OverlayWindow) -> None:
    window.config.only_when_game_foreground.set(True)
    core.monitor.start()
    assert not window.isVisible()

    core.backend.title = "ELDEN RING NIGHTREIGN"
    core.monitor._poll()
    assert window.isVisible()

    core.backend.title = "Explorer"
    core.monitor._poll()
    assert not window.isVisible()

    # Window mode ignores the rule so the overlay stays reachable.
    core.config.overlay_mode.set("window")
    assert window.isVisible()
    core.monitor.stop()


def test_position_is_persisted_and_reset(window: OverlayWindow) -> None:
    window.move(window.pos().x() + 15, window.pos().y() + 10)
    process_events()
    saved = window.config.position.value
    assert saved == [window.pos().x(), window.pos().y()]

    window.reset_position()
    process_events()
    assert window.config.position.value is None
    assert [window.pos().x(), window.pos().y()] != saved

    window.move(window.pos().x() + 15, window.pos().y() + 40)
    process_events()
    saved_y = window.pos().y()
    window.reset_horizontal_position()
    process_events()
    assert window.config.position.value == [None, saved_y]
    assert window.pos().y() == saved_y

    # While horizontally reset, the overlay stays centred when resized.
    center = window.geometry().center().x()
    window.config.scale.set(200)
    process_events()
    assert window.config.position.value == [None, saved_y]
    assert abs(window.geometry().center().x() - center) <= 1


def test_hud_resizes_and_shows_added_widgets(core: Core, store: ConfigStore) -> None:
    overlay = HudOverlay(
        core.overlays,
        store.bind(OverlayConfig, "hud.overlay"),
        store.bind(HudConfig, "plugins.hud"),
        "HUD",
    )
    overlay.show_overlay()
    widget = QWidget()
    widget.setFixedSize(200, 40)

    overlay.add_widget("test", widget, order=0)
    process_events()

    assert overlay.isVisible()
    assert widget.isVisible()
    assert overlay.size().width() >= 200
    assert overlay.size().height() >= 40


def test_hud_scales_contributed_day_timer_content(core: Core, store: ConfigStore) -> None:
    overlay_config = store.bind(OverlayConfig, "hud.overlay")
    overlay = HudOverlay(
        core.overlays,
        overlay_config,
        store.bind(HudConfig, "plugins.hud"),
        "HUD",
    )
    overlay_config.scale.set(150)
    widget = _DayTimerHud([270, 180, 210, 180], "Waiting")
    overlay.add_widget("day_timer", widget, order=0)
    process_events()

    assert widget.width() == 600
    assert all(segment.height() == 24 for segment in widget.segments)
    assert overlay.width() >= widget.width() + 24


def test_overlay_test_plugin_lifecycle(core: Core, store: ConfigStore) -> None:
    manager = PluginManager(store, Translator("en_US"), core.services, core.events)
    manager.discover()
    manager.load_all()
    manager.start()
    assert not manager.is_active("overlay_test")

    manager.set_enabled("overlay_test", True)
    assert manager.is_active("overlay_test")
    [overlay] = [window for window in core.overlays.windows() if isinstance(window, OverlayTestWindow)]
    assert overlay.isVisible()

    api = core.services.require(OverlayTestApi)
    overlay.config.scale.set(200)
    assert overlay.size() == QSize(600, 264)
    api.restart_countdown()

    core.events.publish(GameForegroundChanged(False))
    process_events()

    manager.set_enabled("overlay_test", False)
    record = manager.get("overlay_test")
    assert record is not None and record.state == PluginState.INACTIVE
    assert not any(isinstance(window, OverlayTestWindow) for window in core.overlays.windows())
    assert core.services.get(OverlayTestApi) is None

    manager.set_enabled("overlay_test", True)
    [overlay] = [window for window in core.overlays.windows() if isinstance(window, OverlayTestWindow)]
    # Settings survive a disable / enable cycle.
    assert overlay.size() == QSize(600, 264)
    manager.shutdown()
    assert core.overlays.windows() == []
