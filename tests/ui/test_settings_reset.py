"""Page-level "Reset" button of plugin pages and of the general settings page."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QWidget

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.config import BoolOption, ConfigGroup, ConfigStore, RangeOption
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin import Plugin, PluginManager, PluginManifest, SettingsScope
from nightreign_overlay.plugins.art_timer import plugin as art_plugin
from nightreign_overlay.plugins.art_timer.plugin import ArtTimerPlugin
from nightreign_overlay.plugins.day_timer import plugin as day_plugin
from nightreign_overlay.plugins.day_timer.plugin import DayTimerPlugin
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding, InputDevice
from nightreign_overlay.plugins.rain_timer import plugin as rain_plugin
from nightreign_overlay.plugins.rain_timer.plugin import RainTimerPlugin
from nightreign_overlay.ui.components import (
    ConfigSwitchCard,
    HotkeySettingCard,
    create_reset_button,
    reset_button,
)
from nightreign_overlay.ui.components.setting_cards import _format_binding
from nightreign_overlay.ui.pages.plugin_page import PluginPage
from nightreign_overlay.ui.pages.settings import SettingsPage
from tests.support.feature_fakes import FeatureServices

_ALT_X = HotkeyBinding(InputDevice.KEYBOARD, ("alt", "x"))


def _confirm(monkeypatch: pytest.MonkeyPatch, answer: bool) -> list[bool]:
    asked: list[bool] = []

    def confirm(_parent: QWidget, _content: str) -> bool:
        asked.append(answer)
        return answer

    monkeypatch.setattr(reset_button, "confirm_reset", confirm)
    return asked


class _SampleConfig(ConfigGroup):
    enabled = BoolOption(True)
    level = RangeOption(5, 0, 10)


def _sample_plugin(scope: SettingsScope) -> type[Plugin]:
    class Sample(Plugin):
        manifest = PluginManifest(id="sample", settings_scope=scope)

        def on_load(self) -> None:
            self.config = self.ctx.config(_SampleConfig)
            self.extra = self.ctx.config(_SampleConfig, "extra")

        def create_settings_widget(self, parent: QWidget) -> QWidget:
            return ConfigSwitchCard(self.config.enabled, "", "enabled", parent=parent)

    return Sample


def _manager(store: ConfigStore, plugin_cls: type[Plugin]) -> PluginManager:
    manager = PluginManager(store, Translator("zh_CN"), ServiceRegistry(), EventBus())
    manager.register(plugin_cls)
    manager.load_all()
    return manager


def test_plugin_page_reset_needs_confirmation_and_restores_every_bound_group(
    store: ConfigStore, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(store, _sample_plugin(SettingsScope.PAGE))
    plugin = manager.get("sample").plugin
    page = PluginPage(manager, manager.get("sample"))
    assert page.resetButton is not None
    plugin.config.enabled.set(False)
    plugin.extra.level.set(9)

    asked = _confirm(monkeypatch, False)
    page.resetButton.click()
    assert asked == [False]
    assert (plugin.config.enabled.value, plugin.extra.level.value) == (False, 9)

    _confirm(monkeypatch, True)
    page.resetButton.click()
    assert (plugin.config.enabled.value, plugin.extra.level.value) == (True, 5)
    assert page.findChild(ConfigSwitchCard).switchButton.isChecked()


def test_plugin_page_reset_is_only_shown_on_the_settings_tab(store: ConfigStore, qapp: QApplication) -> None:
    manager = _manager(store, _sample_plugin(SettingsScope.PAGE))
    page = PluginPage(manager, manager.get("sample"))
    page.show()
    assert page.resetButton.isVisible()
    page.segmented.setCurrentItem("tutorial")
    page.stack.setCurrentIndex(1)
    assert not page.resetButton.isVisible()
    page.stack.setCurrentIndex(0)
    assert page.resetButton.isVisible()
    page.close()


def test_plugin_page_without_settings_has_no_reset(store: ConfigStore, qapp: QApplication) -> None:
    class Bare(Plugin):
        manifest = PluginManifest(id="bare")

    manager = _manager(store, Bare)
    assert PluginPage(manager, manager.get("bare")).resetButton is None


def test_general_settings_reset_keeps_internal_state_and_resets_embedded_plugins(
    store: ConfigStore, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = store.bind(AppConfig, "app")
    manager = _manager(store, _sample_plugin(SettingsScope.GENERAL))
    plugin = manager.get("sample").plugin
    page = SettingsPage(config, manager)
    config.theme.set("light")
    config.close_to_tray.set(False)
    config.tray_hint_shown.set(True)
    plugin.config.enabled.set(False)

    _confirm(monkeypatch, True)
    page.resetButton.click()
    assert (config.theme.value, config.close_to_tray.value) == ("dark", True)
    assert config.tray_hint_shown.value is True
    assert plugin.config.enabled.value is True


@pytest.mark.parametrize(
    ("plugin_cls", "module", "region", "actions"),
    [
        (
            DayTimerPlugin,
            day_plugin,
            "day_timer.detect_region",
            {
                "day_timer.next_day": HotkeyBinding(None),
                "day_timer.forward": HotkeyBinding(None),
                "day_timer.backward": HotkeyBinding(None),
                "day_timer.calibrate_region": HotkeyBinding(None),
            },
        ),
        (
            RainTimerPlugin,
            rain_plugin,
            "rain_timer.hp_region",
            {
                "rain_timer.toggle": HotkeyBinding(None),
                "rain_timer.calibrate_region": HotkeyBinding(None),
                "rain_timer.calibrate_color": HotkeyBinding(None),
            },
        ),
        (
            ArtTimerPlugin,
            art_plugin,
            "art_timer.art_region",
            {"art_timer.use_art": HotkeyBinding(None), "art_timer.calibrate_region": HotkeyBinding(None)},
        ),
    ],
)
def test_feature_reset_restores_shortcuts_clears_region_and_refreshes_cards(
    store: ConfigStore,
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plugin_cls: type[Plugin],
    module: object,
    region: str,
    actions: dict[str, HotkeyBinding],
) -> None:
    fakes = FeatureServices(store, tmp_path)
    plugin = plugin_cls(fakes.context(plugin_cls.manifest.id, Path(module.__file__).parent))
    plugin.on_load()
    hotkeys = fakes.services.require(HotkeyApi)
    for action in actions:
        hotkeys.set_binding(action, _ALT_X)
    host = QWidget()
    panel = plugin.create_settings_widget(host)
    fakes.region.save_region_for_test(region, QRect(1, 2, 30, 40))
    other = QRect(5, 5, 5, 5)
    fakes.region.save_region_for_test("other.region", other)
    item = next(iter(plugin.config.items().values()))
    changed = not item.default if isinstance(item.default, bool) else item.option.maximum
    item.set(changed)
    cards = panel.findChildren(HotkeySettingCard)
    assert cards and all(card.captureButton.text() == _format_binding(_ALT_X) for card in cards)

    _confirm(monkeypatch, True)
    button = create_reset_button(plugin.reset_settings, panel, "", panel)
    button.click()
    assert {action: hotkeys.binding(action, HotkeyBinding(None)) for action in actions} == actions
    assert fakes.region.regions == {"other.region": other}
    assert item.value == item.default
    for card in cards:
        assert card.captureButton.text() == _format_binding(card.binding)
        assert card.binding == actions[card._action_id]
