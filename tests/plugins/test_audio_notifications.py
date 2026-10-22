"""Feature scheduling through the same service, independent of HUD rendering."""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QRect

from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.art_timer import plugin as art_module
from nightreign_overlay.plugins.art_timer.plugin import ArtTimerPlugin
from nightreign_overlay.plugins.audio.api import AudioApi
from nightreign_overlay.plugins.day_timer import plugin as day_module
from nightreign_overlay.plugins.day_timer.plugin import DayTimerPlugin
from nightreign_overlay.plugins.hud.api import HudTimerBar
from nightreign_overlay.plugins.rain_timer.plugin import RainTimerPlugin
from nightreign_overlay.plugins.region.api import RegionApi


class RecordingAudio(AudioApi):
    def __init__(self):
        self.calls = []
        self.stops = []
        self.loop_calls = []
        self.loop_stops = []
        self.loop_owners = set()

    def play(self, path, volume=100, *, owner=""):
        if path:
            self.calls.append((owner, path, volume))
        return bool(path)

    def stop(self, owner=None):
        self.stops.append(owner)

    def play_loop(self, path, volume=100, fade_in=0, *, owner=""):
        self.loop_calls.append((owner, path, volume, fade_in))
        self.loop_owners.add(owner)
        return bool(path)

    def stop_loop(self, owner, fade_out=0):
        self.loop_stops.append((owner, fade_out))
        self.loop_owners.discard(owner)

    def set_loop_fade_out(self, owner, seconds):
        pass

    def is_loop_playing(self, owner):
        return owner in self.loop_owners


@pytest.fixture
def make_timer(store, tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(day_module.time, "monotonic", lambda: clock[0])
    audio = RecordingAudio()
    services = ServiceRegistry()
    services.register(AudioApi, audio, owner="audio")

    def make(cls):
        ctx = PluginContext(cls.manifest.id, tmp_path, store, Translator("zh_CN"), services, EventBus())
        instance = cls(ctx)
        instance.on_load()
        for key, cue in instance._audio.cues.items():
            cue.enabled.set(True)
            cue.path.set(f"{key}.wav")
        return instance

    return make, clock, audio


@pytest.mark.parametrize("day", [1, 2, 3])
def test_day_start_delay_and_repeated_banner(make_timer, day):
    make, clock, audio = make_timer
    plugin = make(DayTimerPlugin)
    plugin._audio.cues[f"day{day}"].seconds.set(0.5)
    plugin._detected_day(day)
    assert audio.calls == []
    clock[0] += 0.5
    plugin._update_timer()
    assert audio.calls == [("day_timer", f"day{day}.wav", 100)]
    plugin._detected_day(day)
    clock[0] += 1
    plugin._update_timer()
    assert len(audio.calls) == 1


@pytest.mark.parametrize("day", [1, 2])
def test_circle_advance_forward_and_rewind(make_timer, day):
    make, clock, audio = make_timer
    plugin = make(DayTimerPlugin)
    plugin._audio.cues["first_circle"].seconds.set(5.5)
    plugin._audio.cues["second_circle"].seconds.set(8.5)
    plugin._start_day(day)
    clock[0] += 264.4
    plugin._update_timer()
    assert len(audio.calls) == 1
    plugin._forward("button")
    assert audio.calls[-1][1] == "first_circle.wav"
    plugin._backward("button")
    plugin._forward()
    assert len(audio.calls) == 2
    clock[0] = 1000 + 660 - 8.5
    plugin._update_timer()
    assert audio.calls[-1][1] == "second_circle.wav"
    plugin._start_next_day("button")
    assert audio.calls[-1][1] == f"day{2 if day == 1 else 1}.wav"


def test_rain_manual_start_end_and_cancel_pending_delay(make_timer):
    make, clock, audio = make_timer
    plugin = make(RainTimerPlugin)
    plugin._audio.cues["warning"].enabled.set(False)
    plugin._audio.cues["start"].seconds.set(2.5)
    plugin._audio.cues["end"].seconds.set(5.5)
    plugin._toggle("button")
    clock[0] += 2.5
    plugin._update_timer()
    assert audio.calls[-1][1] == "start.wav"
    clock[0] = 1104.5
    plugin._update_timer()
    assert audio.calls[-1][1] == "end.wav"
    plugin._toggle()
    assert len(audio.calls) == 2
    plugin._toggle()
    plugin._toggle("button")
    assert audio.calls[-1][1] == "end.wav"
    clock[0] += 20
    plugin._update_timer()
    assert len(audio.calls) == 3


def test_rain_default_warning_and_end_are_separate_once_per_run(make_timer):
    make, clock, audio = make_timer
    plugin = make(RainTimerPlugin)
    plugin._start()
    assert [call[1] for call in audio.calls] == ["start.wav"]
    clock[0] = 1079.9
    plugin._update_timer()
    assert len(audio.calls) == 1
    clock[0] = 1080
    plugin._update_timer()
    assert [call[1] for call in audio.calls] == ["start.wav", "warning.wav"]
    clock[0] = 1110
    plugin._update_timer()
    plugin._update_timer()
    plugin._stop()
    assert [call[1] for call in audio.calls] == ["start.wav", "warning.wav", "end.wav"]
    plugin._start()
    clock[0] += 10
    plugin._stop()
    clock[0] += 100
    plugin._update_timer()
    assert [call[1] for call in audio.calls][3:] == ["start.wav", "end.wav"]


@pytest.mark.parametrize("disabled", ["warning", "end"])
def test_rain_individual_switch_does_not_disable_other_cues(make_timer, disabled):
    make, clock, audio = make_timer
    plugin = make(RainTimerPlugin)
    plugin._audio.cues[disabled].enabled.set(False)
    plugin._start()
    clock[0] = 1080
    plugin._update_timer()
    clock[0] = 1110
    plugin._update_timer()
    plugin._stop()
    assert [call[1] for call in audio.calls] == [
        f"{key}.wav" for key in ("start", "warning", "end") if key != disabled
    ]


def test_default_circle_warnings_are_thirty_seconds_early(make_timer):
    make, clock, audio = make_timer
    plugin = make(DayTimerPlugin)
    plugin._start_day(1)
    for elapsed, expected in ((239.9, "day1.wav"), (240, "first_circle.wav"), (630, "second_circle.wav")):
        clock[0] = 1000 + elapsed
        plugin._update_timer()
        assert audio.calls[-1][1] == expected
    assert len(audio.calls) == 3


def test_default_art_warning_is_three_seconds_before_effect_end(make_timer):
    make, clock, audio = make_timer
    plugin = make(ArtTimerPlugin)
    plugin._art_type, plugin._art_started = "scholar", clock[0]
    clock[0] += 2
    plugin._update_timer()
    assert [call[1] for call in audio.calls] == ["start.wav"]
    clock[0] = 1018.9
    plugin._update_timer()
    assert len(audio.calls) == 1
    clock[0] = 1019
    plugin._update_timer()
    assert audio.calls[-1][1] == "end.wav"


def test_art_loop_uses_recognized_role_config_and_countdown_window(make_timer):
    make, clock, audio = make_timer
    plugin = make(ArtTimerPlugin)
    plugin._hud = HudTimerBar("#000000")
    plugin._audio.cues["start"].enabled.set(False)
    plugin._audio.cues["end"].enabled.set(False)
    config = plugin._loop_audio["scholar"]
    config.enabled.set(True)
    config.path.set("scholar-loop.wav")
    config.volume.set(65)
    config.fade_in.set(1.2)
    config.fade_out.set(2.3)
    plugin._art_type, plugin._art_started = "scholar", clock[0]

    clock[0] += 1.9
    plugin._update_timer()
    # The loop starts when the detected countdown is shown, including the
    # activation-delay portion before the effect takes effect.
    assert audio.loop_calls == [("art_timer:art:scholar", "scholar-loop.wav", 65, 1.2)]

    clock[0] += 20.2
    plugin._update_timer()
    assert audio.loop_stops == [("art_timer:art:scholar", 2.3)]
    assert plugin._art_type is None


def test_art_uses_effect_start_and_character_duration(make_timer, monkeypatch):
    make, clock, audio = make_timer
    plugin = make(ArtTimerPlugin)
    plugin._detector = SimpleNamespace(
        detect=lambda *_a, **_kw: SimpleNamespace(
            art_type="scholar",
            scores={},
            best_score=0.0,
        )
    )
    plugin._audio.cues["start"].seconds.set(0.5)
    plugin._audio.cues["end"].seconds.set(3.5)
    monkeypatch.setattr(art_module, "crop_rgb", lambda *_: None)
    frame = SimpleNamespace(image=None, hdr=False)
    region = QRect(0, 0, 50, 50)
    plugin.ctx.services.register(RegionApi, SimpleNamespace(region=lambda _key: region))
    plugin._on_art_frame(frame, region, plugin._detect_generation)
    clock[0] += 2.4
    plugin._update_timer()
    assert audio.calls == []
    clock[0] += 0.1
    plugin._update_timer()
    assert audio.calls[-1][1] == "start.wav"
    clock[0] = 1018.5
    plugin._update_timer()
    assert audio.calls[-1][1] == "end.wav"
    plugin._update_timer()
    assert len(audio.calls) == 2


@pytest.mark.parametrize("cls", [DayTimerPlugin, RainTimerPlugin, ArtTimerPlugin])
def test_disable_cancels_pending_notifications(make_timer, cls):
    make, clock, audio = make_timer
    plugin = make(cls)
    if cls is DayTimerPlugin:
        plugin._start_day(1)
    elif cls is RainTimerPlugin:
        plugin._start()
    else:
        plugin._art_type, plugin._art_started = "duchess", clock[0]
    before = len(audio.calls)
    plugin.on_deactivate()
    clock[0] += 1000
    plugin._update_timer()
    assert len(audio.calls) == before
    assert audio.stops[-1] == plugin.id
