"""Reusable widgets shared by the main window and plugin settings pages."""

from nightreign_overlay.ui.components.overlay_settings import OverlaySettingSection
from nightreign_overlay.ui.components.page import ScrollPage, SettingSection, SettingsPanel
from nightreign_overlay.ui.components.reset_button import create_reset_button
from nightreign_overlay.ui.components.setting_cards import (
    ConfigChoiceCard,
    ConfigColorCard,
    ConfigRangeCard,
    ConfigSwitchCard,
    HotkeySettingCard,
    MultiButtonSettingCard,
)

__all__ = [
    "ConfigChoiceCard",
    "ConfigColorCard",
    "ConfigRangeCard",
    "ConfigSwitchCard",
    "HotkeySettingCard",
    "MultiButtonSettingCard",
    "OverlaySettingSection",
    "ScrollPage",
    "SettingSection",
    "SettingsPanel",
    "create_reset_button",
]
