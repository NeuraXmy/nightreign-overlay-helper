"""Status-meter attack buff lifecycle, fixed checkpoints, HUD, and calibration."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QWidget

from nightreign_overlay.plugins.capture.api import FrameCaptured
from nightreign_overlay.plugins.debuff_timer import plugin as module
from nightreign_overlay.plugins.debuff_timer.plugin import DebuffTimerPlugin
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding, InputDevice
from nightreign_overlay.plugins.region.api import RegionStatus
from nightreign_overlay.plugins.region.automatic import automatic_region
from nightreign_overlay.ui.components import HotkeySettingCard
from nightreign_overlay.ui.components.audio_settings import AudioSettingCard
from tests.support.feature_fakes import FeatureServices, solid_image
from tests.support.qt import delete_qobjects


@pytest.fixture
def feature(store, tmp_path, monkeypatch):
    fakes = FeatureServices(store, tmp_path)
    plugin = DebuffTimerPlugin(fakes.context("debuff_timer", Path(module.__file__).parent))
    plugin.on_load()
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    plugin.on_activate()
    fakes.region.regions[module._REGION_KEY] = QRect(0, 0, 450, 320)
    fakes.capture.frame = FrameCaptured(solid_image(450, 320, (40, 40, 40)), clock[0])
    present = [False]
    calls = []

    def detect(rgb):
        calls.append(rgb)
        return SimpleNamespace(present=present[0])

    monkeypatch.setattr(plugin._detector, "detect", detect)
    bar = plugin._hud
    yield plugin, fakes, clock, present, calls
    plugin.on_deactivate()
    plugin.ctx.release()
    fakes.input.ctx.release()
    bar.close()
    delete_qobjects(bar, plugin, fakes.input)


def start(feature):
    plugin, fakes, _, present, _ = feature
    present[0] = True
    fakes.events.publish(fakes.capture.frame)
    assert plugin._level == 1
    return feature


def test_waiting_uses_shared_stream_and_hud_has_requested_text_and_color(feature):
    plugin, fakes, clock, present, calls = feature
    assert not plugin.manifest.initial_enabled
    assert plugin._hud.isHidden()
    assert fakes.capture.streams == {plugin.id}
    assert fakes.capture.captures == 0
    fakes.events.publish(fakes.capture.frame)
    assert len(calls) == 1 and plugin._level == 0
    present[0] = True
    fakes.events.publish(fakes.capture.frame)
    assert plugin._level == 1 and plugin._deadline == pytest.approx(119.8)
    assert not fakes.capture.streams
    assert plugin._hud.label.text() == "异常量表提升攻击力 Lv.1 下次检测 19.8s"
    assert module._COLOR in plugin._hud.bar.styleSheet()
    clock[0] += 4.8
    plugin._tick()
    assert plugin._hud.label.text() == "异常量表提升攻击力 Lv.1 下次检测 15.0s"
    assert plugin._hud.bar.value() == 7575


def test_disappear_and_reappear_between_checkpoints_do_not_change_cycle(feature):
    plugin, fakes, clock, present, calls = start(feature)
    for elapsed, visible in [(8, False), (17, True), (19.7, False)]:
        clock[0] = 100 + elapsed
        present[0] = visible
        fakes.events.publish(fakes.capture.frame)
        plugin._tick()
        assert plugin._level == 1 and plugin._deadline == pytest.approx(119.8)
    assert len(calls) == 1 and fakes.capture.captures == 0
    present[0] = True
    clock[0] = 119.8
    plugin._tick()
    assert len(calls) == 2 and fakes.capture.captures == 1
    assert plugin._level == 2 and plugin._deadline == pytest.approx(139.8)


def test_caps_at_ten_and_missing_meter_clears_then_restarts(feature, caplog):
    plugin, fakes, clock, present, calls = start(feature)
    for checkpoint in range(1, 13):
        clock[0] = 100 + checkpoint * 20
        plugin._tick()
        assert plugin._level == min(checkpoint + 1, 10)
        assert plugin._hud.bar.value() == 10000
    assert len(calls) == 13
    present[0] = False
    clock[0] += 20
    plugin._tick()
    assert plugin._level == 0 and plugin._deadline is None and plugin._hud.isHidden()
    assert fakes.capture.streams == {plugin.id}
    present[0] = True
    fakes.events.publish(fakes.capture.frame)
    assert plugin._level == 1 and plugin._deadline == pytest.approx(clock[0] + 19.8)


def test_one_pending_request_and_late_callback_cannot_restart_disabled_plugin(feature):
    plugin, fakes, clock, _, calls = start(feature)
    callbacks = []
    fakes.capture.request_frame = callbacks.append
    clock[0] += 20
    plugin._tick()
    plugin._tick()
    assert len(callbacks) == 1
    plugin.on_deactivate()
    plugin.ctx.release()
    callbacks[0](fakes.capture.frame)
    assert plugin._level == 0 and plugin._deadline is None
    assert len(calls) == 1
    assert not plugin._clock.isActive() and not fakes.capture.streams and not fakes.hud.widgets


def test_capture_failure_retries_without_clearing_and_region_change_rejects_frame(feature):
    plugin, fakes, clock, _, calls = start(feature)
    clock[0] += 20
    frame = fakes.capture.frame
    fakes.capture.frame = None
    plugin._tick()
    assert plugin._level == 1 and len(calls) == 1
    plugin._tick()
    assert fakes.capture.captures == 1
    fakes.capture.frame = frame
    clock[0] += 1
    callbacks = []
    fakes.capture.request_frame = callbacks.append
    plugin._tick()
    fakes.region.regions[module._REGION_KEY] = QRect(10, 10, 450, 320)
    callbacks[0](frame)
    assert plugin._level == 1 and len(calls) == 1
    clock[0] += 1
    plugin._tick()
    callbacks[1](frame)  # Region extends outside this frame: not an absent meter.
    assert plugin._level == 1 and len(calls) == 1


def test_calibration_pauses_detection_and_invalidates_pending_request(feature, monkeypatch):
    plugin, fakes, clock, _, calls = start(feature)
    callbacks = []
    fakes.capture.request_frame = callbacks.append
    clock[0] += 20
    plugin._tick()

    def calibrate(*args):
        assert plugin._calibrating
        plugin._tick()
        fakes.events.publish(fakes.capture.frame)
        return None

    monkeypatch.setattr(fakes.region, "request_region", calibrate)
    plugin._calibrate_region()
    callbacks[0](fakes.capture.frame)
    assert len(calls) == 1
    assert not plugin._calibrating and not plugin._pending
    plugin._tick()
    callbacks[1](fakes.capture.frame)
    assert plugin._level == 2


def test_settings_build_before_activation_and_reset_clears_region_and_cycle(store, tmp_path):
    fakes = FeatureServices(store, tmp_path)
    plugin = DebuffTimerPlugin(fakes.context("debuff_timer", Path(module.__file__).parent))
    plugin.on_load()
    host = QWidget()
    panel = plugin.create_settings_widget(host)
    cards = panel.findChildren(HotkeySettingCard)
    assert [card._action_id for card in cards] == [module._CALIBRATE, module._START, module._END]
    card = cards[0]
    (audio_card,) = panel.findChildren(AudioSettingCard)
    assert audio_card.cue is plugin._audio.cues["check"]
    audio_card.spinBox.setValue(3.0)
    assert plugin._audio.cues["check"].seconds.value == 3.0
    (status,) = panel.findChildren(RegionStatus)
    assert status.parent() is card
    assert card._action_id == module._CALIBRATE
    hotkeys = fakes.services.require(HotkeyApi)
    for action in (module._START, module._END):
        hotkeys.set_binding(action, HotkeyBinding(InputDevice.KEYBOARD, ("f8",)))
    fakes.region.regions[module._REGION_KEY] = QRect(1, 2, 450, 320)
    plugin._level, plugin._deadline = 3, 200
    plugin.reset_settings()
    assert not fakes.region.regions and plugin._level == 0 and plugin._deadline is None
    assert fakes.services.require(HotkeyApi).binding(module._CALIBRATE, HotkeyBinding(None)) == HotkeyBinding(
        None
    )
    for action in (module._START, module._END):
        assert hotkeys.binding(action, HotkeyBinding(None)) == HotkeyBinding(None)
    host.close()
    delete_qobjects(host, plugin)
    fakes.input.ctx.release()


def test_default_region_matches_supplied_reference():
    assert automatic_region(module._REGION_KEY, QRect(0, 0, 1960, 1100)) == QRect(730, 360, 450, 320)


def test_manual_hotkeys_start_restart_stop_and_invalidate_pending_checks(feature):
    plugin, fakes, clock, present, calls = feature
    hotkeys = fakes.services.require(HotkeyApi)
    hotkeys.set_binding(module._START, HotkeyBinding(InputDevice.KEYBOARD, ("f8",)))
    hotkeys.set_binding(module._END, HotkeyBinding(InputDevice.KEYBOARD, ("f9",)))

    def trigger(key):
        hotkeys.trigger_for_test(InputDevice.KEYBOARD, (key,))

    # Manual start does not require a detected meter.
    trigger("f8")
    assert plugin._level == 1 and plugin._deadline == pytest.approx(119.8)
    assert not calls and not fakes.capture.streams
    callbacks = []
    fakes.capture.request_frame = callbacks.append
    clock[0] = 120
    plugin._tick()
    assert plugin._pending
    clock[0] = 125
    trigger("f8")
    assert plugin._level == 1 and plugin._deadline == pytest.approx(144.8) and not plugin._pending
    present[0] = True
    callbacks[0](fakes.capture.frame)
    assert not calls and plugin._level == 1 and plugin._deadline == pytest.approx(144.8)

    clock[0] = 145
    plugin._tick()
    trigger("f9")
    assert plugin._level == 0 and plugin._deadline is None and plugin._hud.isHidden()
    assert fakes.capture.streams == {plugin.id}
    callbacks[1](fakes.capture.frame)
    assert not calls and plugin._deadline is None
    # Automatic detection resumes after manually clearing the current cycle.
    fakes.events.publish(fakes.capture.frame)
    assert plugin._level == 1 and plugin._deadline == pytest.approx(164.8)
    plugin.on_deactivate()
    plugin.ctx.release()
    trigger("f8")
    assert plugin._level == 0 and plugin._deadline is None


@pytest.mark.parametrize("advance,trigger_at", [(0.0, 119.8), (3.0, 116.8), (25.0, 100.0)])
def test_checkpoint_audio_advance_once_per_cycle_and_repeats_at_level_ten(
    feature, monkeypatch, advance, trigger_at
):
    plugin, fakes, clock, present, _ = feature
    played = []
    monkeypatch.setattr(fakes.audio, "play", lambda *args, **kwargs: played.append((args, kwargs)) or True)
    cue = plugin._audio.cues["check"]
    assert not cue.enabled.value
    cue.enabled.set(True)
    cue.path.set("reminder.wav")
    cue.volume.set(65)
    cue.seconds.set(advance)
    start(feature)
    if trigger_at > 100:
        clock[0] = trigger_at - 0.1
        plugin._tick()
        assert not played
    clock[0] = trigger_at
    plugin._tick()
    assert played == [(("reminder.wav", 65), {"owner": plugin.id})]
    plugin._tick()
    assert len(played) == 1
    # Each new period, including capped Lv.10, gets its own reminder.
    present[0] = True
    for period in range(1, 12):
        clock[0] = 100 + period * 20
        plugin._tick()
        assert plugin._level == min(10, period + 1)
        clock[0] = max(clock[0], plugin._deadline - advance)
        plugin._tick()
        assert len(played) == period + 1


def test_boundary_audio_finishes_on_absence_but_manual_stop_cancels(feature, monkeypatch):
    plugin, fakes, clock, present, _ = feature
    played, stopped = [], []
    monkeypatch.setattr(fakes.audio, "play", lambda *args, **kwargs: played.append(args) or True)
    monkeypatch.setattr(fakes.audio, "stop", lambda owner=None: stopped.append(owner))
    cue = plugin._audio.cues["check"]
    cue.enabled.set(True)
    cue.path.set("reminder.wav")
    start(feature)
    stopped.clear()
    present[0] = False
    clock[0] = 120
    plugin._tick()
    assert len(played) == 1 and not stopped
    assert plugin._deadline is None
    plugin._manual_end()
    assert stopped == [plugin.id]


def test_failed_checkpoint_does_not_repeat_audio_and_reset_restores_defaults(feature, monkeypatch):
    plugin, fakes, clock, _, _ = feature
    played = []
    monkeypatch.setattr(fakes.audio, "play", lambda *args, **kwargs: played.append(args) or True)
    cue = plugin._audio.cues["check"]
    cue.enabled.set(True)
    cue.path.set("reminder.wav")
    start(feature)
    fakes.capture.frame = None
    for second in (120, 121, 122):
        clock[0] = second
        plugin._tick()
    assert len(played) == 1
    plugin.reset_settings()
    assert not cue.enabled.value and cue.path.value == "" and cue.seconds.value == 0


@pytest.mark.parametrize(
    "selected,expected",
    [
        (QRect(100, 200, 450, 320), QRect(100, 200, 450, 320)),
        (QRect(100, 200, 600, 320), QRect(100, 200, 450, 320)),
        (QRect(100, 200, 450, 500), QRect(100, 290, 450, 320)),
        (QRect(-600, -400, 900, 1000), QRect(-600, -220, 900, 640)),
        (QRect(0, 0, 451, 501), QRect(0, 90, 451, 321)),
    ],
)
def test_calibration_fits_left_center_and_persists_adjusted_region(feature, monkeypatch, selected, expected):
    plugin, fakes, _, _, _ = feature
    monkeypatch.setattr(fakes.region, "request_region", lambda *args: selected)
    saved = []

    def save(key, rect):
        saved.append((key, rect))
        fakes.region.regions[key] = rect

    monkeypatch.setattr(fakes.region, "save_region", save)
    plugin._calibrate_region()
    assert saved == [(module._REGION_KEY, expected)]
    assert fakes.region.region(module._REGION_KEY) == expected
    assert selected.contains(expected)
    assert not plugin._calibrating


def test_canceling_calibration_preserves_previous_region(feature, monkeypatch):
    plugin, fakes, _, _, _ = feature
    previous = QRect(fakes.region.region(module._REGION_KEY))
    monkeypatch.setattr(fakes.region, "request_region", lambda *args: None)
    monkeypatch.setattr(fakes.region, "save_region", lambda *args: pytest.fail("canceled selection saved"))
    plugin._calibrate_region()
    assert fakes.region.region(module._REGION_KEY) == previous
    assert not plugin._calibrating
