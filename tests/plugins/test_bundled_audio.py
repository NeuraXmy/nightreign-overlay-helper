"""Default voices remain portable and never overwrite explicit cue preferences."""

from shutil import copytree

import pytest
import yaml

from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.audio import defaults
from nightreign_overlay.plugins.audio.api import AudioApi, AudioNotifications


def notifications(plugin_id, store, keys, services=None):
    ctx = PluginContext(
        plugin_id,
        store.path.parent,
        store,
        Translator("zh_CN"),
        services or ServiceRegistry(),
        EventBus(),
    )
    return AudioNotifications(ctx, keys)


@pytest.mark.parametrize("identity,preset", defaults.BUNDLED_CUES.items())
def test_fresh_cues_have_bundled_resources_and_independent_reset_defaults(store, identity, preset):
    plugin_id, key = identity
    alerts = notifications(plugin_id, store, (key,))
    cue = alerts.cues[key]
    assert cue.enabled.value is False and cue.path.value == ""
    assert cue.seconds.value == preset.seconds and cue.volume.value == 100
    assert alerts.path_for(cue) == str(preset.path)
    assert preset.path.is_file() and preset.path.stat().st_size > 0
    cue.enabled.set(True)
    cue.path.set("custom.wav")
    cue.volume.set(42)
    cue.seconds.set(9.5)
    alerts.ctx.reset_configs()
    assert cue.enabled.value is False and cue.path.value == ""
    assert cue.seconds.value == preset.seconds and cue.volume.value == 100


@pytest.mark.parametrize("enabled", [True, False])
def test_saved_custom_file_offset_and_enabled_preference_survive_upgrade(store, enabled):
    alerts = notifications("rain_timer", store, ("warning",))
    cue = alerts.cues["warning"]
    cue.path.set("custom.mp3")
    cue.volume.set(24)
    cue.seconds.set(0.0)
    cue.enabled.set(enabled)
    store.flush()
    restored = notifications("rain_timer", ConfigStore(store.path), ("warning",)).cues["warning"]
    assert restored.enabled.value is enabled
    assert (restored.path.value, restored.volume.value, restored.seconds.value) == ("custom.mp3", 24, 0.0)
    restored.reset_all()
    assert not restored.enabled.value and restored.seconds.value == 30.0


def test_existing_custom_end_cue_preserved_when_rain_warning_is_added(store):
    old = notifications("rain_timer", store, ("start", "end"))
    old.cues["end"].path.set("my-rain-end.wav")
    old.cues["end"].seconds.set(4.5)
    store.flush()
    upgraded = notifications("rain_timer", ConfigStore(store.path), ("start", "warning", "end"))
    assert upgraded.cues["end"].path.value == "my-rain-end.wav"
    assert upgraded.cues["end"].seconds.value == 4.5
    assert upgraded.cues["warning"].seconds.value == 30.0
    assert upgraded.path_for(upgraded.cues["warning"]).endswith("rain_warning.mp3")


def test_exported_defaults_resolve_after_unicode_installation_move(store, tmp_path, monkeypatch):
    original = defaults.SOUNDS_DIR
    relocated = tmp_path / "黑夜助手 新目录" / "sounds"
    copytree(original, relocated)
    alerts = notifications("day_timer", store, ("day1", "first_circle"))
    exported = tmp_path / "export.yaml"
    store.export_file(exported)
    data = yaml.safe_load(exported.read_text(encoding="utf-8"))
    assert data["plugins"]["day_timer"]["audio"]["day1"]["path"] == ""
    assert data["plugins"]["day_timer"]["audio"]["first_circle"]["seconds"] == 30.0
    monkeypatch.setattr(defaults, "SOUNDS_DIR", relocated)
    for cue in alerts.cues.values():
        assert alerts.path_for(cue).startswith(str(relocated))
        assert cue.path.value == ""
    custom = str(tmp_path / "missing-custom.mp3")
    alerts.cues["day1"].path.set(custom)
    # A missing custom file is not silently replaced with an unexpected built-in voice.
    assert alerts.path_for(alerts.cues["day1"]) == custom


def test_disabling_one_cue_only_stops_its_own_current_playback(store):
    class Player(AudioApi):
        def __init__(self):
            self.calls = []
            self.owner = ""

        def play(self, path, volume=100, *, owner=""):
            self.calls.append(path)
            self.owner = owner
            return True

        def stop(self, owner=None):
            if owner is None or owner == self.owner:
                self.owner = ""

        def is_playing(self, owner=None):
            return bool(self.owner) and (owner is None or owner == self.owner)

    services = ServiceRegistry()
    player = Player()
    services.register(AudioApi, player)
    alerts = notifications("rain_timer", store, ("start", "warning", "end"), services)
    start, warning, end = (alerts.cues[key] for key in ("start", "warning", "end"))
    for cue in (start, warning, end):
        cue.enabled.set(True)
    alerts.play(start)
    warning.enabled.set(False)
    assert player.owner == "rain_timer"
    start.enabled.set(False)
    assert not player.owner
    alerts.update(100, {"warning": 80})
    warning.enabled.set(True)
    alerts.update(101, {"warning": 80})
    assert len(player.calls) == 1  # Re-enabling must not replay an already consumed warning.
    alerts.play_test(end)
    assert alerts.is_test_playing(end) and not alerts.is_test_playing(warning)
    warning.enabled.set(False)
    assert player.owner == "rain_timer:test"
    end.enabled.set(False)
    assert not player.owner
    alerts.play_test(end)
    assert len(player.calls) == 2
    end.enabled.set(True)
    alerts.play(end)
    player.play("another-feature.mp3", owner="art_timer")
    end.enabled.set(False)
    assert player.owner == "art_timer"
