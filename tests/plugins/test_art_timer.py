"""Coverage for art_timer behaviour that does not need a real game window (no visual detection)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QWidget

from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.plugins.art_timer import plugin as art_plugin
from nightreign_overlay.plugins.art_timer.detector import ART_TYPES, ArtDetectResult
from nightreign_overlay.plugins.art_timer.plugin import ArtTimerPlugin
from nightreign_overlay.plugins.capture.api import FrameCaptured
from nightreign_overlay.plugins.hud.api import HudTimerBar
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.ui.components import ConfigRangeCard
from tests.support.feature_fakes import FeatureServices, solid_image

_ROOT = Path(art_plugin.__file__).parent
_REGION = "art_timer.art_region"


def _plugin(
    store: ConfigStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ArtTimerPlugin, FeatureServices, list[float]]:
    fakes = FeatureServices(store, tmp_path)
    plugin = ArtTimerPlugin(fakes.context("art_timer", _ROOT))
    plugin.on_load()
    clock = [1000.0]
    monkeypatch.setattr(art_plugin.time, "monotonic", lambda: clock[0])
    return plugin, fakes, clock


def test_activation_loads_icons_and_registers_unbound_hotkeys_without_a_stream(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, fakes, _ = _plugin(store, tmp_path, monkeypatch)
    plugin.on_activate()
    assert plugin._detector is not None and plugin._detector.missing() == []
    hotkeys = fakes.services.require(HotkeyApi)
    for action in ("art_timer.use_art", "art_timer.calibrate_region"):
        assert hotkeys.binding(action, HotkeyBinding(None)) == HotkeyBinding(None)
    # Art detection captures single frames on demand instead of keeping the periodic stream alive.
    assert fakes.capture.streams == set()
    [(owner, widget, order)] = fakes.hud.widgets.values()
    assert (owner, order) == ("art_timer", 20)
    assert isinstance(widget, HudTimerBar) and widget.isHidden()

    plugin._use_art()
    plugin.ctx.release()
    plugin.on_deactivate()
    assert fakes.hud.widgets == {}
    assert not plugin._clock.isActive() and not plugin._detect_timer.isActive()


def test_use_art_waits_for_the_delay_and_a_new_press_restarts_it(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    plugin, _, _ = _plugin(store, tmp_path, monkeypatch)
    plugin.config.detect_delay_ms.set(800)
    with caplog.at_level(logging.INFO):
        plugin._use_art()
    assert plugin._detect_timer.isActive() and plugin._detect_timer.interval() == 800
    assert "Will detect art in 0.8 seconds." in caplog.messages
    plugin._use_art()
    assert plugin._detect_timer.isActive()
    plugin._detect_timer.stop()


def _scores(best: str | None, score: float) -> ArtDetectResult:
    scores = {art_type: 0.5 for art_type in ART_TYPES}
    if best is not None:
        scores[best] = score
    return ArtDetectResult(best, score, scores)


def test_detect_art_captures_one_frame_and_starts_the_matching_countdown(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    plugin, fakes, clock = _plugin(store, tmp_path, monkeypatch)
    plugin.on_activate()
    calls: list[tuple] = []
    results = [_scores(None, 0.3), _scores("executor", 0.01)]

    def fake_detect(frame, region, threshold, *, hdr=False):
        calls.append((region, threshold, hdr))
        return results.pop(0)

    monkeypatch.setattr(plugin._detector, "detect", fake_detect)

    plugin._detect_art()  # No region: nothing is captured.
    assert fakes.capture.captures == 0
    fakes.region.regions[_REGION] = QRect(5, 6, 50, 50)
    plugin._detect_art()  # No frame available: the press is dropped.
    assert fakes.capture.captures == 1 and calls == []

    fakes.capture.frame = FrameCaptured(solid_image(100, 100, (0, 0, 0)), 0.0, True)
    with caplog.at_level(logging.INFO):
        plugin._detect_art()
    assert calls == [(QRect(5, 6, 50, 50), 0.02, True)]
    assert plugin._art_type is None
    assert "No art detected, best score: 0.3000" in caplog.messages
    assert "No art detected." in caplog.messages

    with caplog.at_level(logging.INFO):
        plugin._detect_art()
    assert (plugin._art_type, plugin._art_started) == ("executor", clock[0])
    assert "detected art: executor" in caplog.messages
    plugin.ctx.release()


def test_new_art_press_discards_an_in_flight_capture(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, fakes, _ = _plugin(store, tmp_path, monkeypatch)
    plugin.on_activate()
    fakes.region.regions[_REGION] = QRect(5, 6, 50, 50)
    callbacks = []
    calls = []
    fakes.capture.request_frame = callbacks.append
    monkeypatch.setattr(plugin._detector, "detect", lambda *args, **kwargs: calls.append(args))

    plugin._detect_art()
    assert len(callbacks) == 1
    plugin._use_art()
    callbacks[0](FrameCaptured(solid_image(100, 100, (0, 0, 0)), 0.0))
    assert calls == []
    plugin.ctx.release()


@pytest.mark.parametrize(
    ("art_type", "name", "duration", "color"),
    [
        ("duchess", "落幕之章隐身时间", 13, "#cccccc"),
        ("recluse", "血魂歌标记时间", 13, "#d11010"),
        ("revenant", "不死行军无敌时间", 13, "#9bdfdf"),
        ("scholar", "共感术标记时间", 20, "#cecece"),
        ("executor", "熔炉百相变身时间", 15, "#c98941"),
    ],
)
def test_countdown_starts_after_the_legacy_delay_and_clears_when_done(
    store: ConfigStore,
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    art_type: str,
    name: str,
    duration: int,
    color: str,
) -> None:
    plugin, _, clock = _plugin(store, tmp_path, monkeypatch)
    bar = plugin._hud = HudTimerBar("#000000")
    plugin._art_type, plugin._art_started = art_type, clock[0]

    clock[0] += 1.5  # Still within the 2 s activation delay: the bar stays full.
    plugin._update_timer()
    assert bar.label.text() == f"{name} 0:{duration:02d}"
    assert bar.bar.value() == bar.bar.maximum()
    assert color in bar.bar.styleSheet()

    clock[0] += 0.5 + duration / 2
    plugin._update_timer()
    assert bar.bar.value() == bar.bar.maximum() // 2
    assert not bar.isHidden()

    clock[0] += duration / 2 + 0.1
    plugin._update_timer()
    assert bar.isHidden()
    assert plugin._art_type is None


def test_calibrate_region_suspends_detection(
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
    assert fakes.region.requests == [(_REGION, plugin.ctx.tr("settings.region.annotate"), "#3235eb")]
    assert seen == [True] and not plugin._calibrating


def test_settings_page_builds_before_activation_with_advanced_options(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, _, _ = _plugin(store, tmp_path, monkeypatch)
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)
    labels = [card.valueLabel.text() for card in panel.findChildren(ConfigRangeCard)]
    assert labels == ["500 ms", "0.020"]


@pytest.mark.parametrize("change", ["reset", "region"])
def test_reset_or_region_change_discards_in_flight_art(store, tmp_path, monkeypatch, change):
    plugin, fakes, _ = _plugin(store, tmp_path, monkeypatch)
    plugin.on_activate()
    fakes.region.regions[_REGION] = QRect(5, 6, 50, 50)
    callbacks = []
    fakes.capture.request_frame = callbacks.append
    monkeypatch.setattr(plugin._detector, "detect", lambda *_args, **_kwargs: _scores("duchess", 0.01))
    plugin._use_art()
    plugin._detect_art()
    assert len(callbacks) == 1
    if change == "reset":
        plugin.reset_settings()
        assert not plugin._detect_timer.isActive()
    else:
        fakes.region.regions[_REGION] = QRect(15, 6, 50, 50)
    callbacks[0](FrameCaptured(solid_image(100, 100, (0, 0, 0)), 0.0))
    assert plugin._art_type is plugin._art_started is None
    plugin.ctx.release()
