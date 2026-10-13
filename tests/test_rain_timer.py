"""Coverage for rain_timer behaviour that does not need a real game window (no visual detection)."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from feature_fakes import FeatureServices, solid_image
from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.plugins.capture.api import FrameCaptured
from nightreign_overlay.plugins.hud.api import HudTimerBar
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.plugins.rain_timer import plugin as rain_plugin
from nightreign_overlay.plugins.rain_timer.detector import DEFAULT_HLS, RainDetectResult
from nightreign_overlay.plugins.rain_timer.plugin import RainTimerPlugin

_ROOT = Path(rain_plugin.__file__).parent
_REGION = "rain_timer.hp_region"


def _plugin(
    store: ConfigStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[RainTimerPlugin, FeatureServices, list[float]]:
    fakes = FeatureServices(store, tmp_path)
    plugin = RainTimerPlugin(fakes.context("rain_timer", _ROOT))
    plugin.on_load()
    clock = [1000.0]
    monkeypatch.setattr(rain_plugin.time, "monotonic", lambda: clock[0])
    return plugin, fakes, clock


def _bar(plugin: RainTimerPlugin) -> HudTimerBar:
    plugin._hud = HudTimerBar("#f766ba")
    return plugin._hud


def _hls(rgb: tuple[int, int, int]) -> list[int]:
    return [int(value) for value in cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2HLS)[0][0]]


def test_activation_registers_unbound_hotkeys_stream_and_hidden_hud(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, fakes, _ = _plugin(store, tmp_path, monkeypatch)
    plugin.on_activate()
    hotkeys = fakes.services.require(HotkeyApi)
    for action in ("rain_timer.toggle", "rain_timer.calibrate_region", "rain_timer.calibrate_color"):
        assert hotkeys.binding(action, HotkeyBinding(None)) == HotkeyBinding(None)
    assert fakes.capture.streams == {"rain_timer"}
    [(owner, widget, order)] = fakes.hud.widgets.values()
    assert (owner, order) == ("rain_timer", 10)
    assert isinstance(widget, HudTimerBar) and widget.isHidden()

    plugin.ctx.release()
    plugin.on_deactivate()
    assert fakes.capture.streams == set()
    assert fakes.hud.widgets == {}
    assert not plugin._clock.isActive()


def test_toggle_counts_down_like_legacy_and_logs_the_source(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    plugin, _, clock = _plugin(store, tmp_path, monkeypatch)
    bar = _bar(plugin)
    plugin._update_timer()
    assert bar.isHidden()

    with caplog.at_level(logging.INFO):
        plugin._toggle()
    assert not bar.isHidden()
    assert bar.label.text() == "雨中冒险倒计时 1:50 - 0%"
    assert "Started in rain by shortcut." in caplog.messages

    clock[0] += 55
    plugin._update_timer()
    assert bar.label.text() == "雨中冒险倒计时 0:55 - 50%"
    assert bar.bar.value() == bar.bar.maximum() // 2

    # Like the legacy app, an expired countdown only hides; it keeps running until stopped.
    clock[0] += 60
    plugin._update_timer()
    assert bar.isHidden()
    assert plugin._started is not None

    with caplog.at_level(logging.INFO):
        plugin._toggle("button")
    assert plugin._started is None and bar.isHidden()
    assert "Stopped in rain by button." in caplog.messages


def test_auto_detection_starts_and_stops_on_state_changes(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, fakes, clock = _plugin(store, tmp_path, monkeypatch)
    _bar(plugin)
    results: list[RainDetectResult | None] = []
    calls: list[tuple] = []

    def fake_detect(frame, region, not_in_rain, in_rain, tolerance, min_ratio, max_ratio):
        calls.append((region, not_in_rain, in_rain, tolerance, min_ratio, max_ratio))
        return results.pop(0)

    monkeypatch.setattr(rain_plugin, "detect_rain", fake_detect)
    frame = FrameCaptured(solid_image(10, 10, (0, 0, 0)), 0.0, False)

    plugin._on_frame(frame)  # No region yet: nothing is detected.
    assert calls == []

    fakes.region.regions[_REGION] = QRect(1, 2, 3, 4)
    results[:] = [RainDetectResult(True, 0.0, 0.8, 0.01)]
    plugin._on_frame(frame)
    started = plugin._started
    assert started == clock[0]
    assert calls[-1] == (
        QRect(1, 2, 3, 4),
        DEFAULT_HLS[(False, False)],
        DEFAULT_HLS[(True, False)],
        (5, 30, 30),
        0.1,
        0.5,
    )

    clock[0] += 5
    results[:] = [RainDetectResult(True, 0.0, 0.8, 0.01), None, RainDetectResult(None, 0.3, 0.3, 0.01)]
    for _ in range(3):
        plugin._on_frame(frame)
    assert plugin._started == started  # Still in rain or undecided: the countdown is not restarted.

    results[:] = [RainDetectResult(False, 0.8, 0.0, 0.01)]
    plugin._on_frame(frame)
    assert plugin._started is None

    # Disabling auto detection leaves the manual toggle as the only trigger.
    plugin.config.auto_detect.set(False)
    count = len(calls)
    plugin._on_frame(frame)
    assert len(calls) == count


def test_detection_uses_colours_of_the_frame_image_mode(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, fakes, _ = _plugin(store, tmp_path, monkeypatch)
    fakes.region.regions[_REGION] = QRect(0, 0, 5, 5)
    calls: list[tuple] = []
    monkeypatch.setattr(
        rain_plugin, "detect_rain", lambda _frame, _region, normal, rain, *_: calls.append((normal, rain))
    )
    plugin.config.in_rain_hls_hdr.set([150, 90, 60])

    plugin._on_frame(FrameCaptured(solid_image(5, 5, (0, 0, 0)), 0.0, True))
    assert calls[-1] == (DEFAULT_HLS[(False, True)], ([150, 90, 60], [150, 90, 60]))
    plugin._on_frame(FrameCaptured(solid_image(5, 5, (0, 0, 0)), 0.0, False))
    assert calls[-1] == (DEFAULT_HLS[(False, False)], DEFAULT_HLS[(True, False)])


def test_calibrate_region_suspends_detection_and_uses_legacy_annotation(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, fakes, _ = _plugin(store, tmp_path, monkeypatch)
    seen: list[bool] = []
    original = fakes.region.request_region

    def request_region(key, label=None, color=None):
        seen.append(plugin._calibrating)
        return original(key, label, color)

    monkeypatch.setattr(fakes.region, "request_region", request_region)
    plugin._calibrate_region()
    assert fakes.region.requests == [(_REGION, "点我并框出 血条 的区域", "#a84747")]
    assert seen == [True] and not plugin._calibrating


def test_calibrate_color_only_updates_the_current_image_mode(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    plugin, fakes, _ = _plugin(store, tmp_path, monkeypatch)
    fakes.capture.hdr = True
    fakes.region.samples = {"in_rain": solid_image(4, 3, (200, 40, 150))}

    with caplog.at_level(logging.INFO):
        plugin._calibrate_color()
    [targets] = fakes.region.sample_requests
    assert [(target.id, target.label, target.color) for target in targets] == [
        ("not_in_rain", "点我并框出 正常颜色血条 的区域", "#b83232"),
        ("in_rain", "点我并框出 雨中颜色血条 的区域", "#c03184"),
    ]
    assert plugin.config.in_rain_hls_hdr.value == _hls((200, 40, 150))
    assert plugin.config.not_in_rain_hls_hdr.value is None
    assert plugin.config.in_rain_hls.value is None
    assert any(message.startswith("Updated hp color:") for message in caplog.messages)
    assert not plugin._calibrating

    fakes.capture.hdr = False
    fakes.region.samples = None
    with caplog.at_level(logging.WARNING):
        plugin._calibrate_color()
    assert "align hp color setting canceled" in caplog.messages
    assert plugin.config.not_in_rain_hls.value is None


def test_reset_colors_asks_first_and_only_resets_the_current_mode(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, fakes, _ = _plugin(store, tmp_path, monkeypatch)
    for name in ("not_in_rain_hls", "in_rain_hls", "not_in_rain_hls_hdr", "in_rain_hls_hdr"):
        plugin.config.item(name).set([1, 2, 3])
    prompts: list[str] = []
    answer = [False]

    def confirm(_parent, _title, content):
        prompts.append(content)
        return answer[0]

    monkeypatch.setattr(rain_plugin, "_confirm", confirm)
    parent = QWidget()
    fakes.capture.hdr = True
    plugin._reset_colors(parent)
    assert plugin.config.in_rain_hls_hdr.value == [1, 2, 3]

    answer[0] = True
    plugin._reset_colors(parent)
    assert prompts[-1] == "确定要重置HDR模式下的血条颜色设置为默认吗？"
    assert plugin.config.not_in_rain_hls_hdr.value is None and plugin.config.in_rain_hls_hdr.value is None
    assert plugin.config.not_in_rain_hls.value == [1, 2, 3] and plugin.config.in_rain_hls.value == [1, 2, 3]


def test_settings_page_shows_colour_status_and_manual_toggle(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, fakes, _ = _plugin(store, tmp_path, monkeypatch)
    _bar(plugin)
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)
    [card] = panel.findChildren(rain_plugin._HpColorCard)
    assert (card.notInRainLabel.text(), card.inRainLabel.text()) == ("默认", "默认")

    plugin.config.in_rain_hls.set([160, 80, 150])
    assert card.inRainLabel.text() == "已设置"
    assert "background-color: rgb(" in card.inRainLabel.styleSheet()

    fakes.capture.hdr = True
    card.refresh()
    assert (card.notInRainLabel.text(), card.inRainLabel.text()) == ("HDR:默认", "HDR:默认")

    buttons = {button.text(): button for button in panel.findChildren(QPushButton)}
    buttons["开始/停止"].click()
    assert plugin._started is not None
    buttons["开始/停止"].click()
    assert plugin._started is None
