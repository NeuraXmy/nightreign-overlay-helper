"""Coverage for art_timer behaviour that does not need a real game window (no visual detection)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.plugins.art_timer import plugin as art_plugin
from nightreign_overlay.plugins.art_timer.detector import ART_TYPES, ArtDetectResult
from nightreign_overlay.plugins.art_timer.plugin import ArtTimerPlugin
from nightreign_overlay.plugins.capture.api import FrameCaptured
from nightreign_overlay.plugins.hud.api import HudTimerBar
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.ui.components import ConfigRangeCard, SelectableSettingContainer, SettingSection
from nightreign_overlay.ui.components.audio_settings import AudioSettingCard, LoopAudioSettingCard
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


def test_activation_loads_icons_and_registers_hotkeys_and_undertaker_stream(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, fakes, _ = _plugin(store, tmp_path, monkeypatch)
    plugin.on_activate()
    assert plugin._detector is not None and plugin._detector.missing() == []
    hotkeys = fakes.services.require(HotkeyApi)
    for action in ("art_timer.use_art", "art_timer.calibrate_region"):
        assert hotkeys.binding(action, HotkeyBinding(None)) == HotkeyBinding(None)
    # Only Undertaker color detection consumes the continuous stream.
    assert fakes.capture.streams == {"art_timer"}
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
    parent.setLayout(QVBoxLayout())
    panel = plugin.create_settings_widget(parent)
    parent.layout().addWidget(panel)
    labels = [card.valueLabel.text() for card in panel.findChildren(ConfigRangeCard)]
    assert labels == ["80%", "5 s", "500 ms", "0.020"]
    loop_cards = panel.findChildren(LoopAudioSettingCard)
    finite_cards = panel.findChildren(AudioSettingCard)
    assert len(loop_cards) == 5
    assert len(finite_cards) == 2
    audio_section = panel.findChildren(SettingSection)[-1]
    container = audio_section.findChild(SelectableSettingContainer)
    assert container is not None and container.selector.count() == 5
    assert container.stack.count() == 5
    initial_card = container.stack.currentWidget().findChild(LoopAudioSettingCard)
    assert initial_card.config is plugin._loop_audio["duchess"]
    container.selector.setCurrentIndex(3)
    selected_card = container.stack.currentWidget().findChild(LoopAudioSettingCard)
    assert selected_card.config is plugin._loop_audio["scholar"]
    assert container.stack.minimumHeight() >= selected_card.minimumSizeHint().height()
    assert container.frameShape().name == "StyledPanel"
    assert plugin._loop_audio["scholar"].enabled.value is False

    parent.resize(1400, 1000)
    parent.show()
    qapp.processEvents()
    expected_width = container.width()
    selected_card.slider.setValue(75)
    qapp.processEvents()
    container.selector.setCurrentIndex(1)
    qapp.processEvents()
    assert container.width() == expected_width
    container.selector.setCurrentIndex(4)
    qapp.processEvents()
    assert container.width() == expected_width
    parent.close()


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


@pytest.mark.parametrize("hdr", [False, True])
def test_undertaker_continuous_detection_uses_shared_hud_and_does_not_restart(
    store, qapp, tmp_path, monkeypatch, hdr
):
    from PyQt6.QtGui import QImage

    from tests.support.paths import PROJECT_ROOT
    from tests.support.qt import delete_qobjects

    plugin, fakes, clock = _plugin(store, tmp_path, monkeypatch)
    plugin.on_activate()
    hud = plugin._hud
    assert hud is not None and len(fakes.hud.widgets) == 1
    active = QImage(str(PROJECT_ROOT / "tests/data/undertaker_art/0.png"))
    inactive = QImage(str(PROJECT_ROOT / "tests/data/undertaker_art/1.png"))
    fakes.region.regions[_REGION] = active.rect()
    try:
        fakes.events.publish(FrameCaptured(active, clock[0], hdr))
        assert not plugin._detect_timer.isActive()
        assert plugin._undertaker_started == clock[0]
        assert hud.bar.value() == 10000
        assert "送葬者额外绝招时间" in hud.label.text()
        assert hud._color == "#c28aba"
        clock[0] += 2
        fakes.events.publish(FrameCaptured(active, clock[0], hdr))
        assert hud.bar.value() == 6000
        clock[0] += 3
        plugin._update_timer()
        assert hud.isHidden() and plugin._undertaker_started is None
        fakes.events.publish(FrameCaptured(active, clock[0], hdr))
        assert hud.isHidden()  # A held active icon cannot keep restarting the timer.
        fakes.events.publish(FrameCaptured(inactive, clock[0], hdr))
        fakes.events.publish(FrameCaptured(active, clock[0], hdr))
        assert hud.bar.value() == 10000
        fakes.events.publish(FrameCaptured(inactive, clock[0], hdr))
        assert not hud.isHidden() and plugin._undertaker_started == clock[0]
        clock[0] += 1
        fakes.events.publish(FrameCaptured(active, clock[0], hdr))
        assert hud.bar.value() == 8000  # A new active edge cannot reset a running timer.
        fakes.region.regions.pop(_REGION)
        fakes.events.publish(FrameCaptured(inactive, clock[0], hdr))
        assert not hud.isHidden()  # Missing crops also leave the countdown running.
        fakes.region.regions[_REGION] = active.rect()
        plugin.config.undertaker_enabled.set(False)
        assert fakes.capture.streams == set()
        fakes.events.publish(FrameCaptured(active, clock[0], hdr))
        assert hud.isHidden()
        plugin.config.undertaker_enabled.set(True)
        assert fakes.capture.streams == {plugin.id}
        plugin.config.undertaker_duration.set(10)
        fakes.events.publish(FrameCaptured(active, clock[0], hdr))
        clock[0] += 2
        plugin._update_timer()
        assert hud.bar.value() == 8000
        plugin.config.undertaker_pink_percent.set(100)
        fakes.events.publish(FrameCaptured(active, clock[0], hdr))
        assert hud.bar.value() == 8000
        clock[0] += 8
        plugin._update_timer()
        assert hud.isHidden()
    finally:
        plugin.on_deactivate()
        plugin.ctx.release()
        delete_qobjects(hud)
    assert fakes.capture.streams == set()


def test_undertaker_cancel_restores_existing_art_countdown(store, qapp, tmp_path, monkeypatch):
    from tests.support.qt import delete_qobjects

    plugin, _, clock = _plugin(store, tmp_path, monkeypatch)
    plugin.on_activate()
    hud = plugin._hud
    try:
        plugin._art_type = "duchess"
        plugin._art_started = clock[0] - 3
        plugin._undertaker_active = True
        plugin._undertaker_started = clock[0]
        plugin._update_timer()
        assert hud._color == "#c28aba"
        plugin.config.undertaker_enabled.set(False)
        assert "落幕之章" in hud.label.text() and not hud.isHidden()
        assert hud._color == "#cccccc"
    finally:
        plugin.on_deactivate()
        plugin.ctx.release()
        delete_qobjects(hud)


def test_normal_art_audio_expires_while_undertaker_uses_shared_bar(store, qapp, tmp_path, monkeypatch):
    from tests.support.qt import delete_qobjects

    plugin, _, clock = _plugin(store, tmp_path, monkeypatch)
    plugin.on_activate()
    hud = plugin._hud
    stopped = []
    monkeypatch.setattr(plugin, "_stop_loop", lambda **kwargs: stopped.append(kwargs))
    try:
        plugin._art_type = "duchess"
        plugin._art_started = clock[0] - 14
        plugin._undertaker_active = True
        plugin._undertaker_started = clock[0]
        clock[0] += 2
        plugin._update_timer()
        assert plugin._art_type is None and plugin._art_started is None
        assert stopped == [{}]
        assert hud._color == "#c28aba" and hud.bar.value() == 6000
        plugin.config.undertaker_enabled.set(False)
        assert hud.isHidden()
    finally:
        plugin.on_deactivate()
        plugin.ctx.release()
        delete_qobjects(hud)
