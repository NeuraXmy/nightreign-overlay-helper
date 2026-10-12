"""Overlay window behaviour and the overlay_test plugin running against the real core services."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QApplication

from conftest import process_events
from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.game_window import GameForegroundChanged, GameWindowMonitor
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.platforms import PlatformBackend
from nightreign_overlay.plugin import PluginManager, PluginState
from nightreign_overlay.plugins.overlay_test.api import OverlayTestApi
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
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    core.config.overlay_mode.set("window")
    assert not core.overlays.transparent_mode
    assert not window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.isVisible()
    core.config.overlay_mode.set("overlay")
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint


def test_click_through_only_in_transparent_mode(core: Core, window: OverlayWindow) -> None:
    window.config.click_through.set(True)
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

    # While on the default position the overlay stays horizontally centred when resized.
    center = window.geometry().center().x()
    window.config.scale.set(200)
    process_events()
    assert window.config.position.value is None
    assert abs(window.geometry().center().x() - center) <= 1


def test_overlay_test_plugin_lifecycle(core: Core, store: ConfigStore) -> None:
    manager = PluginManager(store, Translator("en_US"), core.services, core.events)
    manager.discover()
    manager.load_all()
    manager.start()

    assert manager.is_active("overlay_test")
    [overlay] = core.overlays.windows()
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
    assert core.overlays.windows() == []
    assert core.services.get(OverlayTestApi) is None

    manager.set_enabled("overlay_test", True)
    assert len(core.overlays.windows()) == 1
    # Settings survive a disable / enable cycle.
    assert core.overlays.windows()[0].size() == QSize(600, 264)
    manager.shutdown()
    assert core.overlays.windows() == []
