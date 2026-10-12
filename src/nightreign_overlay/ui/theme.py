"""Theme helpers bridging :class:`AppConfig` and qfluentwidgets."""

from __future__ import annotations

from PyQt6.QtGui import QColor, QIcon
from qfluentwidgets import FluentIcon, Theme, setTheme, setThemeColor

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.paths import resource_path

_THEMES = {"dark": Theme.DARK, "light": Theme.LIGHT, "auto": Theme.AUTO}


def apply_theme(config: AppConfig) -> None:
    """Apply the configured theme now and whenever it changes."""
    setTheme(_THEMES[config.theme.value])
    setThemeColor(QColor(config.theme_color.value))
    config.theme.valueChanged.connect(lambda value: setTheme(_THEMES[value], lazy=True))
    config.theme_color.valueChanged.connect(lambda value: setThemeColor(QColor(value)))


def app_icon() -> QIcon:
    return QIcon(str(resource_path("icons", "app.ico")))


def fluent_icon(name: str) -> FluentIcon:
    """Resolve a ``FluentIcon`` member by name, falling back to a generic icon."""
    return FluentIcon.__members__.get(name, FluentIcon.APPLICATION)
