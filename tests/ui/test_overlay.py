"""Overlay windows and shared HUD behaviour against real core services."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QApplication, QWidget

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.game_window import ForegroundPolicy, GameWindowMonitor
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.platforms import PlatformBackend
from nightreign_overlay.plugins.day_timer.plugin import _DayTimerHud
from nightreign_overlay.plugins.hud.api import HudTimerBar
from nightreign_overlay.plugins.hud.config import HudConfig
from nightreign_overlay.plugins.hud.overlay import HudOverlay
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayManager, OverlayWindow
from tests.support.platform import FakeBackend
from tests.support.qt import process_events


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
        (ForegroundPolicy, overlays.foreground),
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


def test_all_transparent_overlays_request_native_nonactivation(core, store, monkeypatch):
    calls = []
    monkeypatch.setattr(
        core.backend, "configure_overlay_activation", lambda hwnd, enabled: calls.append(enabled)
    )
    overlay = OverlayWindow(core.overlays, store.bind(OverlayConfig, "activation"), "test", QSize(200, 100))
    assert calls == [True]
    overlay.config.input_mode.set("passthrough")
    overlay.config.input_mode.set("normal")
    assert calls[-1] is True
    core.config.overlay_mode.set("window")
    assert calls[-1] is False


def test_drag_hint_background_tracks_main_window_and_input_mode(core: Core, window: OverlayWindow) -> None:
    window.drag_hint_enabled = True

    def pixel(x: int, y: int):
        process_events()
        image = window.grab().toImage()
        ratio = image.devicePixelRatio()
        return image.pixelColor(round(x * ratio), round(y * ratio))

    assert pixel(20, 20).alpha() == 0
    core.overlays.foreground.set_ui_active("tray_menu", True)
    assert pixel(20, 20).alpha() == 0
    core.overlays.foreground.set_ui_active("main_window", True)
    fill = pixel(20, 20)
    assert fill.red() == 255
    assert 0 < fill.alpha() < 100
    assert pixel(0, 20).alpha() > fill.alpha()
    for mode in ("locked", "passthrough"):
        window.config.input_mode.set(mode)
        assert pixel(20, 20).alpha() == 0
    window.config.input_mode.set("normal")
    assert pixel(20, 20).alpha() > 0
    core.overlays.foreground.set_ui_active("main_window", False)
    assert pixel(20, 20).alpha() == 0
    # Windows following detected geometry (map / HP) leave the opt-in disabled.
    window.drag_hint_enabled = False
    core.overlays.foreground.set_ui_active("main_window", True)
    assert pixel(20, 20).alpha() == 0


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
    core.config.only_when_game_foreground.set(True)
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


def test_foreground_rule_is_global_and_ui_keeps_overlays_visible(
    core: Core, window: OverlayWindow, store: ConfigStore
) -> None:
    other = OverlayWindow(core.overlays, store.bind(OverlayConfig, "other"), "other", QSize(50, 50))
    other.show_overlay()
    policy = core.overlays.foreground
    core.monitor.start()  # game in the background
    assert window.isVisible() and other.isVisible()

    core.config.only_when_game_foreground.set(True)
    assert not window.isVisible() and not other.isVisible()
    assert not policy.detection_allowed and not policy.input_allowed

    # Legacy is_setting_opened / is_menu_opened: using the app keeps overlays and hotkeys, not detection.
    for source in ("main_window", "tray_menu", "overlay_menu", "region_selection"):
        policy.set_ui_active(source, True)
        assert window.isVisible() and other.isVisible()
        assert policy.input_allowed and not policy.detection_allowed
        policy.set_ui_active(source, False)
        assert not window.isVisible()

    core.overlays.mainWindowHideRequested.emit()
    assert window.isVisible()
    core.overlays.mainWindowShowRequested.emit()
    assert not window.isVisible()
    other.dispose()
    core.monitor.stop()


def test_own_hide_reasons_win_over_the_foreground_exemption(core: Core, store: ConfigStore) -> None:
    config = store.bind(HudConfig, "plugins.hud")
    overlay = HudOverlay(core.overlays, store.bind(OverlayConfig, "hud.overlay"), config, "HUD")
    overlay.add_widget("test", QWidget(), order=0)
    core.config.only_when_game_foreground.set(True)
    core.overlays.foreground.set_ui_active("main_window", True)
    core.monitor.start()
    assert overlay.isVisible()

    config.enabled.set(False)
    assert not overlay.isVisible()
    overlay.hide_overlay()
    config.enabled.set(True)
    assert not overlay.isVisible()
    core.monitor.stop()


def test_position_is_persisted_and_reset(window: OverlayWindow) -> None:
    window.move(window.pos().x() + 15, window.pos().y() + 10)
    process_events()
    saved = window.config.position.value
    assert saved == [window.pos().x(), window.pos().y()]

    window.reset_position()
    process_events()
    assert window.config.position.value == [window.x(), window.y()]
    assert [window.pos().x(), window.pos().y()] != saved

    window.move(window.pos().x() + 15, window.pos().y() + 40)
    process_events()
    saved_y = window.pos().y()
    window.reset_horizontal_position()
    process_events()
    assert window.config.position.value == [window.x(), saved_y]
    assert window.pos().y() == saved_y

    # Resizing preserves the top-center anchor after a horizontal reset.
    saved_anchor = (window.x() + window.width() // 2, window.y())
    window.config.scale.set(200)
    process_events()
    assert window.config.position.value == [window.x(), saved_y]
    assert (window.x() + window.width() // 2, window.y()) == saved_anchor


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


def test_hud_hide_text_hides_labels_but_keeps_progress(core: Core, store: ConfigStore) -> None:
    config = store.bind(HudConfig, "plugins.hud")
    overlay = HudOverlay(core.overlays, store.bind(OverlayConfig, "hud.overlay"), config, "HUD")
    overlay.show_overlay()
    widget = _DayTimerHud([270, 180, 210, 180], "Waiting")
    overlay.add_widget("day_timer", widget, order=0)
    process_events()
    full_height = overlay.height()

    config.hide_text.set(True)
    process_events()
    assert not widget.label.isVisible()
    assert all(segment.isVisible() for segment in widget.segments)
    assert overlay.height() < full_height

    # Widgets added while the setting is on start with their text hidden.
    late = _DayTimerHud([270, 180, 210, 180], "Waiting")
    overlay.add_widget("other", late, order=1)
    process_events()
    assert not late.label.isVisible()

    config.hide_text.set(False)
    process_events()
    assert widget.label.isVisible() and late.label.isVisible()


def test_hud_refits_when_a_contributed_bar_hides_itself(core: Core, store: ConfigStore) -> None:
    overlay = HudOverlay(
        core.overlays, store.bind(OverlayConfig, "hud.overlay"), store.bind(HudConfig, "plugins.hud"), "HUD"
    )
    overlay.show_overlay()
    overlay.add_widget("day_timer", _DayTimerHud([270, 180, 210, 180], "Waiting"), order=0)
    bar = HudTimerBar("#f766ba")
    overlay.add_widget("rain_timer", bar, order=10)
    bar.set_progress(0.5, "rain")
    process_events()
    full_height = overlay.height()

    bar.set_progress(0.0, "")
    process_events()
    assert bar.isHidden()
    assert overlay.height() < full_height

    bar.set_progress(0.5, "rain")
    process_events()
    # Qt layout rounding can vary slightly after a child is shown again.
    assert abs(overlay.height() - full_height) <= 2


@pytest.mark.parametrize("visible", [True, False])
def test_reset_buttons_persist_without_dragging(window, core, store, visible):
    from PyQt6.QtWidgets import QPushButton

    from nightreign_overlay.ui.components.overlay_settings import OverlaySettingSection

    section = OverlaySettingSection(window.config)
    buttons = section.findChildren(QPushButton)
    window.move(window.x() + 30, window.y() + 60)
    process_events()
    if not visible:
        window.hide()
    buttons[1].click()
    process_events()
    horizontal = [window.x(), window.y()]
    store.flush()
    reloaded = ConfigStore(store.path)
    config = reloaded.bind(OverlayConfig, window.config.namespace)
    assert config.position.value == horizontal
    restored = OverlayWindow(core.overlays, config, "restored", window.base_size)
    assert [restored.x(), restored.y()] == horizontal
    restored.dispose()
    reloaded.deleteLater()
    buttons[0].click()
    process_events()
    saved = [window.x(), window.y()]
    store.flush()
    reloaded = ConfigStore(store.path)
    config = reloaded.bind(OverlayConfig, window.config.namespace)
    assert config.position.value == saved
    restored = OverlayWindow(core.overlays, config, "restored", window.base_size)
    assert [restored.x(), restored.y()] == saved
    restored.dispose()
    reloaded.deleteLater()
    section.deleteLater()


@pytest.mark.parametrize("reset", [True, False])
def test_hud_anchor_survives_content_changes_and_restart(core, store, reset):
    config = store.bind(OverlayConfig, "hud.anchor")
    hud_config = store.bind(HudConfig, "plugins.hud")
    overlay = HudOverlay(core.overlays, config, hud_config, "HUD")
    overlay.show_overlay()
    widget = QWidget()
    widget.setFixedSize(200, 40)
    overlay.add_widget("test", widget, order=0)
    process_events()
    if reset:
        config.reset_position()
    else:
        overlay.move(100, 180)
        process_events()
    anchor = (overlay.x() + overlay.width() // 2, overlay.y())
    wider = QWidget()
    wider.setFixedSize(300, 70)
    overlay.add_widget("wider", wider, order=1)
    process_events()
    assert (overlay.x() + overlay.width() // 2, overlay.y()) == anchor
    config.scale.set(125)
    process_events()
    assert (overlay.x() + overlay.width() // 2, overlay.y()) == anchor
    store.flush()
    overlay.dispose()
    reloaded = ConfigStore(store.path)
    restored = HudOverlay(core.overlays, reloaded.bind(OverlayConfig, "hud.anchor"), hud_config, "HUD")
    restored.show_overlay()
    replacement = QWidget()
    replacement.setFixedSize(350, 40)
    restored.add_widget("test", replacement, order=0)
    process_events()
    assert (restored.x() + restored.width() // 2, restored.y()) == anchor
    restored.dispose()
    reloaded.deleteLater()
