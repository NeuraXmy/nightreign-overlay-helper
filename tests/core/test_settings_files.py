"""Complete settings snapshots and atomic restoration before restart."""

import pytest
import yaml

from nightreign_overlay.core import config as config_module
from nightreign_overlay.core.audio import AudioCueConfig
from nightreign_overlay.core.config import BoolOption, ConfigGroup, ConfigStore, RangeOption


class SampleConfig(ConfigGroup):
    enabled = BoolOption(True)
    level = RangeOption(5, 0, 10)


def test_export_includes_defaults_unsaved_changes_and_all_namespaces(store, tmp_path):
    cfg = store.bind(SampleConfig, "app")
    cue = store.bind(AudioCueConfig, "plugins.day_timer.audio.day1")
    cue.path.set("提示音.wav")
    cfg.level.set(8)
    path = tmp_path / "export.yaml"
    store.export_file(path)
    exported = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert exported["app"] == {"enabled": True, "level": 8}
    assert exported["plugins"]["day_timer"]["audio"]["day1"] == {
        "enabled": True,
        "path": "提示音.wav",
        "volume": 100,
        "seconds": 0.0,
    }


def test_export_preserves_unknown_settings_and_latest_duplicate_binding(tmp_path, qapp):
    path = tmp_path / "settings.yaml"
    path.write_text("future_plugin: {value: 7}\napp: {level: 6}\n", encoding="utf-8")
    store = ConfigStore(path)
    first = store.bind(SampleConfig, "app")
    store.bind(SampleConfig, "app")
    first.level.set(9)
    target = tmp_path / "export.yaml"
    store.export_file(target)
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert data["future_plugin"] == {"value": 7}
    assert data["app"]["level"] == 9


def test_replace_resets_missing_settings_and_survives_shutdown_writes(store, tmp_path):
    cfg = store.bind(SampleConfig, "app")
    cue = store.bind(AudioCueConfig, "plugins.rain_timer.audio.start")
    cfg.enabled.set(False)
    cue.path.set("old.wav")
    source = tmp_path / "import.yaml"
    source.write_text("\ufeffapp: {level: 7}\nfuture_plugin: {value: 42}\n", encoding="utf-8")
    imported = store.read_import_file(source)
    assert cfg.enabled.value is False
    store.replace_for_restart(imported)
    cfg.level.set(9)
    store.flush()
    data = yaml.safe_load(store.path.read_text(encoding="utf-8"))
    assert data == {"app": {"level": 7}, "future_plugin": {"value": 42}}
    reloaded = ConfigStore(store.path)
    fresh = reloaded.bind(SampleConfig, "app")
    assert fresh.enabled.value is True and fresh.level.value == 7
    assert reloaded.bind(AudioCueConfig, "plugins.rain_timer.audio.start").path.value == ""


@pytest.mark.parametrize(
    "text",
    [
        "",
        "null",
        "[]",
        "{unrelated: 5}",
        "app: 3",
        "app: {enabled: broken}",
        "app: {level: .inf}",
        "app: {level: .nan}",
        "app: [",
        "app: &loop {child: *loop}",
        "app: {1: value}",
        "app: {date: 2026-01-01}",
        "!!python/object:object {}",
    ],
)
def test_invalid_import_never_changes_settings(store, tmp_path, text):
    cfg = store.bind(SampleConfig, "app")
    cfg.level.set(8)
    store.flush()
    before = store.path.read_bytes()
    path = tmp_path / "bad.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises((ValueError, yaml.YAMLError)):
        store.read_import_file(path)
    assert store.path.read_bytes() == before and cfg.level.value == 8


def test_import_write_failure_keeps_current_file_and_store_writable(store, monkeypatch):
    cfg = store.bind(SampleConfig, "app")
    cfg.level.set(8)
    store.flush()
    before = store.path.read_bytes()
    original_replace = config_module.os.replace

    def fail(*_args):
        raise PermissionError("read only destination")

    monkeypatch.setattr(config_module.os, "replace", fail)
    with pytest.raises(PermissionError):
        store.replace_for_restart({"app": {"level": 3}})
    assert store.path.read_bytes() == before
    assert not list(store.path.parent.glob(".settings.yaml.*.tmp"))
    monkeypatch.setattr(config_module.os, "replace", original_replace)
    cfg.level.set(9)
    store.flush()
    assert yaml.safe_load(store.path.read_text(encoding="utf-8"))["app"]["level"] == 9
