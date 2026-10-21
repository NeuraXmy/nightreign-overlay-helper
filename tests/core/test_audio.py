"""Cue configuration persistence and once-per-run scheduling."""

import pytest

from nightreign_overlay.core.audio import AudioCueConfig, AudioTimeline
from nightreign_overlay.core.config import ConfigStore


@pytest.mark.parametrize("enabled", [True, False])
def test_defaults_persistence_and_reset(store, enabled):
    cue = store.bind(AudioCueConfig, "audio.example")
    assert (cue.path.value, cue.volume.value, cue.seconds.value) == ("", 100, 0.0)
    assert cue.enabled.value is False
    cue.enabled.set(enabled)
    cue.path.set("提示音.wav")
    cue.volume.set(35)
    cue.seconds.set(1.7)
    store.flush()
    restored = ConfigStore(store.path).bind(AudioCueConfig, "audio.example")
    assert restored.enabled.value is enabled
    assert (restored.path.value, restored.volume.value, restored.seconds.value) == ("提示音.wav", 35, 1.7)
    cue.reset_all()
    assert cue.enabled.value is False
    assert (cue.path.value, cue.volume.value, cue.seconds.value) == ("", 100, 0.0)


@pytest.mark.parametrize("value", [float("nan"), "bad", None, True])
def test_invalid_offset_falls_back_to_default(value):
    cue = AudioCueConfig("audio", {"seconds": value}, lambda *_: None)
    assert cue.seconds.value == 0.0


def test_deadlines_rewind_restart_and_jump(store):
    first = store.bind(AudioCueConfig, "audio.first")
    second = store.bind(AudioCueConfig, "audio.second")
    calls = []
    timeline = AudioTimeline(calls.append)
    cues = [("end", 10.5, second), ("start", 1.5, first)]
    timeline.update(1.4, cues)
    assert calls == []
    timeline.update(1.5, cues)
    timeline.update(0, cues)
    timeline.update(11, cues)
    timeline.update(12, cues)
    assert calls == [first, second]
    timeline.reset()
    timeline.update(15, cues)
    assert calls == [first, second, first, second]


def test_advance_longer_than_duration_fires_immediately(store):
    cue = store.bind(AudioCueConfig, "audio.end")
    calls = []
    AudioTimeline(calls.append).update(0, [("end", -5, cue)])
    assert calls == [cue]
