"""Main-program UI/lifecycle checks with macOS mock data; no Steam or ETW execution."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QPushButton, QWidget

from conftest import process_events
from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.game_window import GameWindowMonitor
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.platforms import PlatformBackend
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.p2p_latency.config import P2PConfig, P2POverlayConfig
from nightreign_overlay.plugins.p2p_latency.mock_helper import snapshot
from nightreign_overlay.plugins.p2p_latency.models import P2PPeer, P2PStatus, parse_helper_message
from nightreign_overlay.plugins.p2p_latency.overlay import P2POverlay
from nightreign_overlay.plugins.p2p_latency.plugin import P2PLatencyPlugin, _StatusLabel
from nightreign_overlay.plugins.p2p_latency.service import P2PService
from nightreign_overlay.ui.components import ConfigRangeCard, MultiButtonSettingCard
from nightreign_overlay.ui.overlay import OverlayManager

_ROOT = Path(__file__).parents[1] / "src/nightreign_overlay/plugins/p2p_latency"


class _Backend(PlatformBackend):
    name = "mock"
    supports_foreground_detection = True

    def foreground_window_title(self) -> str | None:
        return None


@pytest.fixture
def plugin(store: ConfigStore):
    translator = Translator("zh_CN")
    translator.load_dir("p2p_latency", _ROOT / "i18n")
    services = ServiceRegistry()
    events = EventBus()
    app_config = store.bind(AppConfig, "app")
    monitor = GameWindowMonitor(_Backend(), events)
    manager = OverlayManager(monitor._backend, app_config, monitor)
    services.register(OverlayManager, manager)
    services.register(AppConfig, app_config)
    ctx = PluginContext("p2p_latency", _ROOT, store, translator, services, events)
    instance = P2PLatencyPlugin(ctx)
    instance.on_load()
    yield instance
    ctx.release()
    for window in manager.windows():
        window.dispose()


def _window(plugin: P2PLatencyPlugin) -> P2POverlay:
    window = P2POverlay(
        plugin.ctx.services.require(OverlayManager), plugin.overlay_config, plugin.config, plugin.ctx.tr
    )
    plugin.ctx.on_cleanup(window.dispose)
    return window


def _peers() -> list[P2PPeer]:
    return [
        P2PPeer("1", "玩家一", None, None, "legacy", "connecting"),
        P2PPeer("2", "玩家二", 80, 0.935, "messages", "connected"),
        P2PPeer("3", "玩家三", 150, 0.64, "legacy", "connected"),
    ]


def _row(window: P2POverlay, row: int, column: int) -> QLabel:
    return window.peer_grid.itemAtPosition(row, column).widget()


def _wait_until(predicate, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        process_events(30)
    assert predicate()


def test_settings_changes_persistence_and_reset(plugin, store, tmp_path):
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)
    assert plugin.overlay_config.opacity.value == 75
    assert plugin.overlay_config.scale.value == 100
    cards = {card.item.key: card for card in panel.findChildren(ConfigRangeCard)}
    cards["opacity"].slider.setValue(10)
    cards["scale"].slider.setValue(175)
    cards["good_ping"].slider.setValue(200)
    assert plugin.config.warning_ping.value == 201
    assert cards["warning_ping"].slider.value() == 201
    cards["warning_ping"].slider.setValue(90)
    assert plugin.config.warning_ping.value == 201
    assert cards["warning_ping"].slider.value() == 201
    plugin.overlay_config.position.set([123, 456])
    store.flush()
    reloaded = ConfigStore(store.path)
    assert reloaded.bind(P2POverlayConfig, "plugins.p2p_latency.overlay").opacity.value == 10
    assert reloaded.bind(P2POverlayConfig, "plugins.p2p_latency.overlay").position.value == [123, 456]
    assert reloaded.bind(P2PConfig, "plugins.p2p_latency").warning_ping.value == 201
    plugin.reset_settings()
    assert cards["opacity"].slider.value() == 75
    assert cards["scale"].slider.value() == 100
    assert cards["good_ping"].slider.value() == 80
    assert cards["warning_ping"].slider.value() == 150
    assert plugin.overlay_config.position.value is None
    parent.deleteLater()
    reloaded.deleteLater()


def test_overlay_rows_missing_metrics_and_colour_boundaries(plugin):
    window = _window(plugin)
    window.set_status(P2PStatus("steam_ready", "模拟", etw_state="simulated"))
    window.set_peers(_peers())
    process_events()
    assert window.isVisible()
    assert _row(window, 0, 1).text() == "-- ms"
    assert _row(window, 0, 2).text() == "--"
    assert "#b8b8b8" in _row(window, 0, 1).styleSheet()
    assert "#f3ca52" in _row(window, 1, 1).styleSheet()
    assert "#ff6464" in _row(window, 2, 1).styleSheet()
    assert _row(window, 1, 2).text() == "94%"
    assert "ETW STUN" in _row(window, 2, 0).toolTip()
    assert not window.status_label.isVisible()
    plugin.config.good_ping.set(100)
    assert "#62d26f" in _row(window, 1, 1).styleSheet()
    window.set_peers([])
    process_events()
    assert window.peer_grid.count() == 0
    assert window.status_label.isVisible()
    window.set_status(P2PStatus("steam_api_error", "模拟初始化失败"))
    assert window.status_label.text() == "模拟初始化失败"


def test_scaling_layout_position_opacity_and_modes(plugin):
    window = _window(plugin)
    window.set_status(P2PStatus("steam_ready", "模拟"))
    window.set_peers(_peers())
    for scale in (50, 100, 200, 125, 57):
        plugin.overlay_config.scale.set(scale)
        process_events()
        assert window.width() == int(240 * scale / 100)
        assert window.height() > 30 * scale / 100
        last_row = _row(window, 2, 2)
        assert last_row.mapTo(window, QPoint(0, last_row.height())).y() <= window.height()
    plugin.overlay_config.opacity.set(10)
    assert window.windowOpacity() == pytest.approx(0.1, abs=0.01)
    assert not window.windowFlags() & Qt.WindowType.WindowTransparentForInput
    window.move(123, 234)
    process_events()
    assert plugin.overlay_config.position.value == [123, 234]
    window.reset_position()
    assert window.pos() == window._default_position()
    plugin.ctx.services.require(AppConfig).overlay_mode.set("window")
    process_events()
    assert window.isVisible()
    assert window.windowFlags() & Qt.WindowType.WindowTitleHint
    plugin.ctx.services.require(AppConfig).overlay_mode.set("auto")
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint


def test_foreground_gate_also_controls_waiting_status(plugin):
    window = _window(plugin)
    manager = window.manager
    config = plugin.ctx.services.require(AppConfig)
    config.only_when_game_foreground.set(True)
    window.set_status(P2PStatus("steam_ready", "模拟"))
    assert not window.isVisible()
    manager.foreground.set_ui_active("main_window", True)
    assert window.isVisible()
    assert "background: transparent" in window.panel.styleSheet()
    manager.foreground.set_ui_active("main_window", False)
    assert not window.isVisible()
    manager.foreground.set_ui_active("tray_menu", True)
    assert window.isVisible()
    window.set_status(P2PStatus("waiting_for_game", "等待"))
    assert window.isVisible()
    manager.foreground.set_ui_active("tray_menu", False)
    assert not window.isVisible()
    manager.foreground.set_ui_active("main_window", True)
    assert window.isVisible()
    assert window.status_label.text() == "等待"


def test_transparent_text_status_and_standard_window_settings(plugin):
    window = _window(plugin)
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)
    assert "background: transparent" in window.panel.styleSheet()
    assert window.status_label.isVisible()
    assert isinstance(window.status_label.graphicsEffect(), QGraphicsDropShadowEffect)
    window.set_status(P2PStatus("steam_ready", "模拟"))
    window.set_peers(_peers())
    process_events()
    assert not window.status_label.isVisible()
    assert len([label for label in window.panel.findChildren(QLabel) if label.isVisible()]) == 9
    assert isinstance(_row(window, 0, 0).graphicsEffect(), QGraphicsDropShadowEffect)
    for state in ("waiting_for_game", "steam_api_error", "helper_missing", "runtime_error"):
        window.set_status(P2PStatus(state, "状态详情"))
        assert window.status_label.isVisible()
        assert window.status_label.text() == "状态详情"
        assert window.peer_grid.count() == 0
    window.set_status(P2PStatus("steam_ready", "模拟"))
    assert window.peer_grid.count() == 9
    plugin.overlay_config.input_mode.set("passthrough")
    assert window.windowFlags() & Qt.WindowType.WindowTransparentForInput
    plugin.overlay_config.input_mode.set("locked")
    assert not window.windowFlags() & Qt.WindowType.WindowTransparentForInput
    reset = panel.findChild(MultiButtonSettingCard)
    buttons = reset.findChildren(QPushButton)
    assert len(buttons) == 1
    plugin.overlay_config.position.set([123, 234])
    buttons[0].click()
    assert plugin.overlay_config.position.value == [window.x(), window.y()]
    assert window.pos() == window._default_position()
    parent.deleteLater()


def test_mock_scenarios_update_rows_order_and_status(plugin):
    import json

    window = _window(plugin)
    service = P2PService()
    service.status_changed.connect(window.set_status)
    service.peers_changed.connect(window.set_peers)
    service._set_status("steam_ready", "模拟", "simulated")
    service._set_peers(parse_helper_message(json.dumps({"type": "snapshot", "peers": snapshot(6)}))[1])
    assert [p.steam_id for p in window.peers] == ["10001", "10002"]
    service._set_peers(parse_helper_message(json.dumps({"type": "snapshot", "peers": snapshot(16)}))[1])
    assert [p.steam_id for p in window.peers] == ["10001", "10003"]
    assert service.status.peer_count == 2
    parent = QWidget()
    label = _StatusLabel(plugin.ctx.tr, parent)
    label.set_status(service.status)
    assert "模拟数据（未启用 ETW）" in label.text()
    assert "当前队友：2" in label.text()
    service._set_peers([])
    assert window.peer_grid.count() == 0
    assert service.status.peer_count == 0
    service.deleteLater()
    parent.deleteLater()


def test_mock_full_cycle_keeps_text_visible_and_fits_rows(plugin):
    window = _window(plugin)
    window.manager.foreground.set_ui_active("main_window", True)
    window.set_status(P2PStatus("steam_ready", "模拟", etw_state="simulated"))
    process_events()
    waiting_height = window.height()
    for tick in range(64):
        peers = parse_helper_message(json.dumps({"type": "snapshot", "peers": snapshot(tick)}))[1]
        window.set_peers(peers)
        # Service updates status immediately after updating the peer count.
        window.set_status(P2PStatus("steam_ready", "模拟", etw_state="simulated", peer_count=len(peers)))
        process_events()
        assert window.isVisible()
        for label in window.panel.findChildren(QLabel):
            if label.isVisible():
                required_height = (
                    label.heightForWidth(label.width()) if label.wordWrap() else label.sizeHint().height()
                )
                assert label.height() >= required_height, (tick, label.text(), window.height())
                assert label.mapTo(window, QPoint(0, label.height())).y() <= window.height()
        if tick == 6:
            assert window.height() > waiting_height
        if tick == 6:
            assert _row(window, 0, 1).text() != "-- ms"
            assert _row(window, 1, 1).text() == "76 ms"


def test_real_mock_subprocess_hot_toggle_and_shutdown(plugin, monkeypatch):
    import nightreign_overlay.plugins.p2p_latency.service as service_module

    monkeypatch.setattr(service_module.sys, "platform", "darwin")
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)
    label = panel.findChild(_StatusLabel)
    plugin.on_activate()
    first = plugin._service
    assert first.process.program() == service_module.sys.executable
    assert first.process.arguments()[-1].endswith("mock_helper.py")
    _wait_until(lambda: bool(first.peers))
    assert first.status.etw_state == "simulated"
    assert plugin._window.isVisible()
    assert "macOS 模拟数据" in label.text()
    assert "当前队友：1" in label.text()
    # Foreground restrictions do not stop network polling.
    plugin.ctx.services.require(AppConfig).only_when_game_foreground.set(True)
    assert not plugin._window.isVisible()
    assert first.process.state() != first.process.ProcessState.NotRunning
    plugin.on_deactivate()
    plugin.ctx.release()
    assert first.process.state() == first.process.ProcessState.NotRunning
    assert first.process.exitCode() == 0
    assert not first.restart_timer.isActive()
    assert plugin._service is None
    assert plugin._window is None
    assert "联机信息已关闭" in label.text()
    assert not plugin.ctx.services.require(OverlayManager).windows()
    plugin.on_activate()
    second = plugin._service
    assert second is not first
    _wait_until(lambda: second.status.state == "steam_ready")
    plugin.ctx.release()
    assert second.process.state() == second.process.ProcessState.NotRunning
    assert second.process.exitCode() == 0
    parent.deleteLater()


def test_long_peer_names_are_elided_and_metrics_stay_inside_window(plugin):
    window = _window(plugin)
    window.set_status(P2PStatus("steam_ready", "模拟"))
    long_name = "这是一个非常非常长的玩家名字 Long player name"
    window.set_peers([P2PPeer("1", long_name, 999, 1.0, "messages", "connected")])
    for scale in (50, 100, 125, 200):
        plugin.overlay_config.scale.set(scale)
        process_events()
        name = _row(window, 0, 0)
        assert name.width() == int(110 * scale / 100)
        assert name.text().endswith("…")
        assert long_name in name.toolTip()
        for column in (1, 2):
            label = _row(window, 0, column)
            assert label.mapTo(window, QPoint(label.width(), 0)).x() <= window.width()
    window.set_peers([P2PPeer("1", "Alice", 80, 0.9, "messages", "connected")])
    assert _row(window, 0, 0).text() == "Alice"
