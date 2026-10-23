from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QWidget

from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.audio.api import AudioApi
from nightreign_overlay.plugins.entertainment.plugin import EntertainmentPlugin
from nightreign_overlay.plugins.input.api import HotkeyApi
from nightreign_overlay.plugins.region.api import RegionApi


class _Region(RegionApi):
    def __init__(self):
        self.rect = QRect(0, 0, 320, 160)

    def region(self, key):
        return self.rect

    def save_region(self, key, rect):
        self.rect = rect

    def clear_region(self, key):
        self.rect = None


class _Audio(AudioApi):
    def set_loop_fade_out(self, owner, seconds):
        pass

    def stop_loop(self, owner, fade_out=0):
        pass

    def is_loop_playing(self, owner):
        return False


class _Hotkeys(HotkeyApi):
    def register(self, action_id, default, callback):
        pass

    def unregister(self, action_id):
        pass

    def binding(self, action_id, default):
        return default


@pytest.fixture
def recovery_playback(store, qapp, tmp_path, monkeypatch):
    import nightreign_overlay.plugins.entertainment.plugin as module
    from nightreign_overlay.plugins.entertainment.detector import Teammate
    from tests.support.feature_fakes import FeatureServices

    fakes = FeatureServices(store, tmp_path)
    plugin = EntertainmentPlugin(
        fakes.context("entertainment", Path("src/nightreign_overlay/plugins/entertainment"))
    )
    plugin.on_load()
    plugin.config.stable_detections.set(1)
    plugin.config.detect_enabled.set(True)
    region, self_region = QRect(0, 0, 240, 120), QRect(250, 0, 115, 115)
    fakes.region.regions.update({"entertainment.teammates": region, "entertainment.self_down": self_region})
    clock, calls = [100.0], []
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    down = Teammate(True, True, 3, 1, (0, 0))
    absent = Teammate(False, False, 0, 0, (0, 0))
    upright = Teammate(True, False, 0, 1, (0, 0))

    def start():
        plugin._playing = True
        calls.append("start")

    def stop(immediate=False):
        plugin._playing = False
        calls.append(("stop", immediate))

    def frame(self_down=False, teammates=(down, down)):
        plugin._on_completed((plugin._generation, teammates, self_down, self_region), region)

    monkeypatch.setattr(plugin, "_start_loop", start)
    monkeypatch.setattr(plugin, "_stop_loop", stop)
    try:
        yield SimpleNamespace(
            plugin=plugin,
            clock=clock,
            calls=calls,
            frame=frame,
            down=down,
            absent=absent,
            upright=upright,
        )
    finally:
        plugin.on_deactivate()
        plugin.ctx.release()


def test_repeated_down_restarts_wait_from_next_confirmed_revival(recovery_playback):
    r = recovery_playback
    r.frame(False)
    r.frame(True)
    r.clock[0] = 101
    r.frame(False)
    r.clock[0] = 107.9
    r.frame(False)
    assert not r.plugin._playing
    r.frame(True)
    r.clock[0] = 108
    r.frame(False)
    r.clock[0] = 108.1  # The first revival would already have allowed playback.
    r.frame(False)
    assert not r.plugin._playing
    r.clock[0] = 114.999
    r.frame(False)
    assert not r.plugin._playing
    r.clock[0] = 115
    r.frame(False)
    assert r.calls == ["start", ("stop", True), "start"]


def test_zero_recovery_delay_allows_immediate_revival_playback(recovery_playback):
    r = recovery_playback
    r.plugin.config.self_recovery_delay.set(0)
    r.frame(False)
    r.frame(True)
    r.frame(False)
    assert r.calls == ["start", ("stop", True), "start"]


@pytest.mark.parametrize("delay", (2, 10))
def test_recovery_delay_changes_apply_to_current_wait(recovery_playback, delay):
    r = recovery_playback
    r.frame(False)
    r.frame(True)
    r.frame(False)
    r.clock[0] = 103
    r.plugin.config.self_recovery_delay.set(delay)
    assert r.plugin._playing == (delay == 2)
    if delay == 2:
        r.plugin.config.self_recovery_delay.set(60)
        assert r.plugin._playing  # An expired wait cannot be reactivated.
    else:
        r.clock[0] = 107
        r.frame(False)
        assert not r.plugin._playing
        r.clock[0] = 110
        r.frame(False)
        assert r.plugin._playing


@pytest.mark.parametrize("state", ("absent", "upright", "single_teammate"))
def test_recovery_expiry_still_requires_teammate_start_conditions(recovery_playback, state):
    r = recovery_playback
    r.frame(False)
    r.frame(True)
    r.frame(False)
    if state == "single_teammate":
        r.plugin.config.three_player_only.set(True)
        teammates = (r.down, r.absent)
    else:
        mate = getattr(r, state)
        teammates = (mate, mate)
    r.clock[0] = 107
    r.frame(False, teammates)
    assert not r.plugin._playing
    r.clock[0] = 108
    r.frame(False)
    assert r.plugin._playing


def test_disabling_self_detection_cancels_revival_wait(recovery_playback):
    r = recovery_playback
    r.frame(False)
    r.frame(True)
    r.frame(False)
    assert not r.plugin._playing
    r.plugin.config.self_down_stop.set(False)
    assert r.plugin._playing
    r.plugin.config.self_down_stop.set(True)
    r.frame(False)
    assert r.calls == ["start", ("stop", True), "start"]


@pytest.mark.parametrize("shutdown", ("disable", "deactivate"))
def test_detection_restart_clears_revival_wait(recovery_playback, shutdown):
    r = recovery_playback
    r.frame(False)
    r.frame(True)
    r.frame(False)
    assert not r.plugin._playing
    if shutdown == "disable":
        r.plugin.config.detect_enabled.set(False)
    else:
        r.plugin.on_deactivate()
        r.plugin.config.detect_enabled.set(False)
    r.plugin.config.detect_enabled.set(True)
    r.frame(False)
    assert r.plugin._playing


def test_plugin_registers_default_region_and_builds_settings(store, qapp, tmp_path):
    services = ServiceRegistry()
    region = _Region()
    services.register(RegionApi, region, owner="region")
    services.register(AudioApi, _Audio(), owner="audio")
    services.register(HotkeyApi, _Hotkeys(), owner="input")
    translator = Translator("zh_CN")
    translator.load_dir("entertainment", Path("src/nightreign_overlay/plugins/entertainment/i18n"))
    translator.load_dir("core", Path("src/nightreign_overlay/resources/i18n"))
    context = PluginContext("entertainment", tmp_path, store, translator, services, EventBus())
    plugin = EntertainmentPlugin(context)
    plugin.on_load()
    plugin.on_activate()
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)

    # Migrate the old fake calibration so the region falls back to automatic 16:9 geometry.
    assert region.rect is None
    assert panel is not None
    section = panel.sectionLayout.itemAt(0).widget()
    titles = [section.cardLayout.itemAt(i).widget().titleLabel.text() for i in range(8)]
    assert titles[3:8] == [
        "播放结束条件",
        "循环播放音频",
        "自身倒地停止播放",
        "自身倒地区域",
        "仅三人游戏时触发",
    ]
    assert plugin.config.self_down_stop.value is True
    advanced = panel.sectionLayout.itemAt(1).widget()
    recovery = advanced.cardLayout.itemAt(1).widget()
    assert recovery.titleLabel.text() == "自身倒地起身后恢复播放时间"
    assert recovery.valueLabel.text() == "7 s"
    assert recovery.slider.minimum() == 0 and recovery.slider.maximum() == 60
    recovery.slider.setValue(12)
    assert plugin.config.self_recovery_delay.value == 12
    plugin.config.self_recovery_delay.set(15)
    assert recovery.slider.value() == 15
    plugin.reset_settings()
    assert plugin.config.self_recovery_delay.value == 7

    plugin.on_deactivate()
    context.release()
    parent.deleteLater()


def test_state_transition_requires_three_consecutive_matching_detections(store, qapp, tmp_path, monkeypatch):
    import nightreign_overlay.plugins.entertainment.plugin as module

    services = ServiceRegistry()
    region = _Region()
    services.register(RegionApi, region, owner="region")
    services.register(AudioApi, _Audio(), owner="audio")
    services.register(HotkeyApi, _Hotkeys(), owner="input")
    translator = Translator("zh_CN")
    translator.load_dir("entertainment", Path("src/nightreign_overlay/plugins/entertainment/i18n"))
    translator.load_dir("core", Path("src/nightreign_overlay/resources/i18n"))
    context = PluginContext("entertainment", tmp_path, store, translator, services, EventBus())
    plugin = EntertainmentPlugin(context)
    plugin.on_load()
    plugin._active = True
    plugin._generation = 1

    from nightreign_overlay.plugins.entertainment.detector import Teammate

    down = Teammate(True, True, 1, 1.0, (0.0, 0.0))
    upright = Teammate(True, False, 0, 1.0, (0.0, 0.0))
    calls = []
    monkeypatch.setattr(plugin, "_start_loop", lambda: calls.append("start"))
    monkeypatch.setattr(module, "should_start", lambda *_: True)
    for _ in range(2):
        plugin._on_completed((1, (down, upright)), region.rect)
    assert calls == []
    plugin._on_completed((1, (down, upright)), region.rect)
    assert calls == ["start"]
    context.release()


def test_self_down_debounce_stops_and_revival_waits_without_log_spam(
    store, qapp, tmp_path, monkeypatch, caplog
):
    import logging

    import nightreign_overlay.plugins.entertainment.plugin as module
    from nightreign_overlay.plugins.entertainment.detector import Teammate
    from tests.support.feature_fakes import FeatureServices

    fakes = FeatureServices(store, tmp_path)
    plugin = EntertainmentPlugin(
        fakes.context("entertainment", Path("src/nightreign_overlay/plugins/entertainment"))
    )
    plugin.on_load()
    plugin._active = True
    fakes.region.regions["entertainment.teammates"] = QRect(0, 0, 240, 120)
    fakes.region.regions["entertainment.self_down"] = QRect(250, 0, 115, 115)
    region = fakes.region.regions["entertainment.teammates"]
    self_region = fakes.region.regions["entertainment.self_down"]
    down = Teammate(True, True, 3, 1.0, (0, 0))
    absent = Teammate(False, False, 0, 0, (0, 0))
    calls = []
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    def start():
        calls.append("start")
        plugin._playing = True

    def stop(immediate=False):
        calls.append(("stop", immediate))
        plugin._playing = False

    monkeypatch.setattr(plugin, "_start_loop", start)
    monkeypatch.setattr(plugin, "_stop_loop", stop)

    def frame(self_down, result=(down, down)):
        plugin._on_completed((plugin._generation, result, self_down, self_region), region)

    with caplog.at_level(logging.INFO):
        for _ in range(3):
            frame(False)
        assert calls == ["start"]
        frame(True)
        frame(False)  # A noisy observation cannot change the confirmed state.
        frame(True)
        frame(True)
        assert calls == ["start"]
        frame(True)
        assert calls[-1] == ("stop", True)
        for _ in range(5):
            frame(True)
        assert len(calls) == 2
        frame(False)
        frame(False)
        assert not plugin._playing
        frame(False)
        assert calls == ["start", ("stop", True)]
        clock[0] = 106.999
        frame(False)
        assert not plugin._playing
        clock[0] = 107.0
        frame(False)
        assert calls == ["start", ("stop", True), "start"]
        for _ in range(4):
            frame(False)
        logs = [message for message in caplog.messages if message.startswith("Self status changed:")]
        assert logs == [
            "Self status changed: upright",
            "Self status changed: down",
            "Self status changed: upright",
        ]
        # Disabling self detection removes its blocking effect and ignores old jobs.
        for _ in range(3):
            frame(True)
        stale_generation = plugin._generation
        plugin.config.self_down_stop.set(False)
        assert plugin._playing
        plugin._on_completed((stale_generation, (down, down), True, self_region), region)
        assert plugin._playing
        for _ in range(3):
            frame(True, (absent, absent))
        assert not plugin._playing  # No teammates still takes precedence.
    plugin._active = False
    plugin.ctx.release()


def test_capture_worker_detects_self_only_when_enabled_and_resets_regions(store, qapp, tmp_path, monkeypatch):
    import time

    import nightreign_overlay.plugins.entertainment.plugin as module
    from nightreign_overlay.plugins.capture.api import FrameCaptured
    from nightreign_overlay.plugins.entertainment.detector import Teammate
    from tests.support.feature_fakes import FeatureServices, solid_image

    fakes = FeatureServices(store, tmp_path)
    plugin = EntertainmentPlugin(
        fakes.context("entertainment", Path("src/nightreign_overlay/plugins/entertainment"))
    )
    plugin.on_load()
    fakes.region.regions["entertainment.teammates"] = QRect(0, 0, 200, 100)
    fakes.region.regions["entertainment.self_down"] = QRect(210, 0, 115, 115)
    down = Teammate(True, True, 3, 1, (0, 0))
    teammate_counts = []
    monkeypatch.setattr(
        module,
        "detect_rgb",
        lambda image, **kwargs: teammate_counts.append(kwargs.get("teammate_count", 2)) or (down, down),
    )
    self_calls = []
    monkeypatch.setattr(module, "is_down", lambda image: self_calls.append(image.shape) or True)
    plugin.config.detect_enabled.set(True)
    plugin.config.stable_detections.set(1)
    plugin.on_activate()
    event = FrameCaptured(solid_image(400, 200, (90, 60, 120)), 0)

    def frame():
        plugin._on_frame(event)
        deadline = time.monotonic() + 2
        while plugin._pending and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.001)
        assert not plugin._pending

    try:
        frame()
        assert self_calls == [(115, 115, 3)]
        assert plugin._self_down is True
        assert teammate_counts == [2]
        from types import SimpleNamespace

        from nightreign_overlay.plugins.p2p_latency.api import PeerSnapshot

        fakes.events.publish(PeerSnapshot((SimpleNamespace(state="connected"),), ""))
        frame()
        assert teammate_counts[-1] == 1
        plugin.config.self_down_stop.set(False)
        frame()
        assert len(self_calls) == 2 and plugin._self_down is None
        plugin._calibrate_self()
        assert fakes.region.requests[-1][0] == "entertainment.self_down"
        plugin.reset_settings()
        assert plugin.config.self_down_stop.value is True
        assert fakes.region.regions == {}
    finally:
        plugin.on_deactivate()
        plugin.ctx.release()
    assert not fakes.capture.streams


def test_three_player_only_blocks_single_teammate_and_rechecks_on_toggle(store, qapp, tmp_path, monkeypatch):
    from nightreign_overlay.plugins.entertainment.detector import Teammate
    from tests.support.feature_fakes import FeatureServices

    fakes = FeatureServices(store, tmp_path)
    plugin = EntertainmentPlugin(
        fakes.context("entertainment", Path("src/nightreign_overlay/plugins/entertainment"))
    )
    plugin.on_load()
    plugin._active = True
    down = Teammate(True, True, 3, 1, (0, 0))
    absent = Teammate(False, False, 0, 0, (0, 0))
    calls = []

    def start():
        plugin._playing = True
        calls.append("start")

    def stop(immediate=False):
        plugin._playing = False
        calls.append("stop")

    monkeypatch.setattr(plugin, "_start_loop", start)
    monkeypatch.setattr(plugin, "_stop_loop", stop)
    assert plugin.config.three_player_only.value is False
    plugin._confirmed_result = (down, absent)
    plugin._apply_playback()
    assert calls == ["start"]
    plugin.config.three_player_only.set(True)
    assert calls == ["start", "stop"]
    plugin._apply_playback()
    assert not plugin._playing
    plugin._confirmed_result = (down, down)
    plugin._apply_playback()
    assert plugin._playing
    plugin._confirmed_result = (absent, absent)
    plugin._apply_playback()
    assert not plugin._playing
    plugin._confirmed_result = (down, absent)
    plugin._apply_playback()
    assert not plugin._playing
    plugin.config.three_player_only.set(False)
    assert plugin._playing
    plugin._active = False
    plugin.ctx.release()


def test_fresh_connected_p2p_roster_limits_detection_and_falls_back_on_failure(
    store, qapp, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import nightreign_overlay.plugins.entertainment.plugin as module
    from nightreign_overlay.plugins.p2p_latency.api import P2PStateChanged, PeerSnapshot
    from tests.support.feature_fakes import FeatureServices

    fakes = FeatureServices(store, tmp_path)
    plugin = EntertainmentPlugin(
        fakes.context("entertainment", Path("src/nightreign_overlay/plugins/entertainment"))
    )
    plugin.on_load()
    plugin.on_activate()
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    connected = SimpleNamespace(state="connected")
    connecting = SimpleNamespace(state="connecting")

    def snapshot(peers):
        fakes.events.publish(PeerSnapshot(tuple(peers), ""))

    try:
        assert plugin._teammate_limit() == 2
        snapshot([connected])
        assert plugin._teammate_limit() == 1
        snapshot([connected, connected])
        assert plugin._teammate_limit() == 2
        snapshot([connecting])
        assert plugin._teammate_limit() == 2
        snapshot([connected])
        clock[0] += 6
        assert plugin._teammate_limit() == 2
        snapshot([connected])
        assert plugin._teammate_limit() == 1
        for state in ("disabled", "helper_error", "helper_restarting", "game_exited", "waiting_for_game"):
            snapshot([connected])
            fakes.events.publish(P2PStateChanged(SimpleNamespace(state=state)))
            assert plugin._teammate_limit() == 2
        snapshot([])
        assert plugin._teammate_limit() == 2
    finally:
        plugin.on_deactivate()
        plugin.ctx.release()
    assert plugin._teammate_limit() == 2
