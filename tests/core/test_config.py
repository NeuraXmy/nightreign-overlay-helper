from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nightreign_overlay.core.config import (
    BoolOption,
    ChoiceOption,
    ColorOption,
    ConfigGroup,
    ConfigStore,
    Option,
    RangeOption,
)


class SampleConfig(ConfigGroup):
    enabled = BoolOption(True)
    opacity = RangeOption(90, 10, 100)
    ratio = RangeOption(0.5, 0.0, 1.0)
    mode = ChoiceOption("auto", ("auto", "manual"))
    color = ColorOption("#C8A35A")
    tags = Option[list[str]]([], validator=lambda v: isinstance(v, list))


class ExtendedConfig(SampleConfig):
    extra = BoolOption(False)


def test_defaults(store: ConfigStore) -> None:
    cfg = store.bind(SampleConfig, "sample")
    assert cfg.enabled.value is True
    assert cfg.opacity.value == 90
    assert cfg.mode.value == "auto"
    assert cfg.tags.value == []


def test_range_option_clamps_and_keeps_type(store: ConfigStore) -> None:
    cfg = store.bind(SampleConfig, "sample")
    cfg.opacity.set(500)
    assert cfg.opacity.value == 100
    cfg.opacity.set(42.6)
    assert cfg.opacity.value == 43 and isinstance(cfg.opacity.value, int)
    cfg.ratio.set(2)
    assert cfg.ratio.value == 1.0 and isinstance(cfg.ratio.value, float)


@pytest.mark.parametrize(
    ("name", "value"),
    [("enabled", 1), ("opacity", True), ("opacity", "50"), ("mode", "other"), ("color", "red")],
)
def test_invalid_values_are_rejected(store: ConfigStore, name: str, value: object) -> None:
    cfg = store.bind(SampleConfig, "sample")
    before = cfg.item(name).value
    with pytest.raises(ValueError):
        cfg.item(name).set(value)
    assert cfg.item(name).value == before


def test_choice_default_must_be_valid() -> None:
    with pytest.raises(ValueError):
        ChoiceOption("x", ("a", "b"))


def test_color_is_normalized(store: ConfigStore) -> None:
    cfg = store.bind(SampleConfig, "sample")
    cfg.color.set("#AABBCC")
    assert cfg.color.value == "#aabbcc"


def test_value_changed_only_on_effective_change(store: ConfigStore) -> None:
    cfg = store.bind(SampleConfig, "sample")
    received: list[object] = []
    cfg.opacity.valueChanged.connect(received.append)
    cfg.opacity.set(90)
    cfg.opacity.set(50)
    cfg.opacity.set(50)
    cfg.opacity.reset()
    assert received == [50, 90]


def test_mutable_defaults_are_not_shared(store: ConfigStore) -> None:
    a = store.bind(SampleConfig, "a")
    b = store.bind(SampleConfig, "b")
    a.tags.value.append("leak")
    assert b.tags.value == []
    assert SampleConfig.tags.default == []


def test_options_are_inherited_in_order() -> None:
    assert list(ExtendedConfig.options()) == ["enabled", "opacity", "ratio", "mode", "color", "tags", "extra"]


def test_round_trip(tmp_path: Path, store: ConfigStore) -> None:
    cfg = store.bind(SampleConfig, "plugins.sample.overlay")
    cfg.opacity.set(30)
    cfg.mode.set("manual")
    store.flush()

    data = yaml.safe_load(store.path.read_text(encoding="utf-8"))
    # Only changed values are written, under the nested namespace.
    assert data == {"plugins": {"sample": {"overlay": {"opacity": 30, "mode": "manual"}}}}

    reloaded = ConfigStore(store.path).bind(SampleConfig, "plugins.sample.overlay")
    assert reloaded.opacity.value == 30
    assert reloaded.mode.value == "manual"
    assert reloaded.enabled.value is True


def test_invalid_stored_value_falls_back_to_default(tmp_path: Path, qapp: object) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("sample:\n  opacity: loud\n  mode: manual\n", encoding="utf-8")
    cfg = ConfigStore(path).bind(SampleConfig, "sample")
    assert cfg.opacity.value == 90
    assert cfg.mode.value == "manual"


def test_corrupted_file_is_backed_up(tmp_path: Path, qapp: object) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    cfg = ConfigStore(path).bind(SampleConfig, "sample")
    assert cfg.opacity.value == 90
    assert not path.exists()
    assert len(list(tmp_path.glob("settings.broken-*.yaml"))) == 1


def test_changes_are_saved_after_debounce(store: ConfigStore) -> None:
    from tests.support.qt import process_events

    cfg = store.bind(SampleConfig, "sample")
    cfg.enabled.set(False)
    assert not store.path.exists()
    process_events(ConfigStore.SAVE_DELAY_MS + 200)
    assert yaml.safe_load(store.path.read_text(encoding="utf-8")) == {"sample": {"enabled": False}}
