"""Application level (non plugin) settings."""

from __future__ import annotations

from nightreign_overlay.core.config import (
    BoolOption,
    ChoiceOption,
    ColorOption,
    ConfigGroup,
    Option,
    RangeOption,
)
from nightreign_overlay.core.i18n import available_languages
from nightreign_overlay.core.log import LOG_LEVELS

APP_CONFIG_NAMESPACE = "app"

THEMES = ("dark", "light", "auto")
#: ``auto`` prefers the legacy frameless transparent overlay; users may explicitly select ``window``.
OVERLAY_MODES = ("auto", "overlay", "window")


class AppConfig(ConfigGroup):
    language = ChoiceOption("auto", ("auto", *available_languages()))
    theme = ChoiceOption("dark", THEMES)
    theme_color = ColorOption("#2e3f7b")
    overlay_mode = ChoiceOption("auto", OVERLAY_MODES)
    #: Legacy "仅在游戏时显示和检测": one switch for every overlay, detection and hotkeys.
    only_when_game_foreground = BoolOption(False)
    # Retained for existing config files; closing hides the window and explicit quit exits the app.
    close_to_tray = BoolOption(True)
    start_minimized = BoolOption(False)
    master_volume = RangeOption(100, 0, 100)
    auto_check_updates = BoolOption(True)
    skipped_update_version = Option("", validator=lambda value: isinstance(value, str))
    debug_images_enabled = BoolOption(True)
    log_level = ChoiceOption("INFO", LOG_LEVELS)
    #: Internal: the "still running in the tray" hint is shown only once.
    tray_hint_shown = BoolOption(False)
