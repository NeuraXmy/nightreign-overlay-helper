"""Plugin system public API."""

from nightreign_overlay.plugin.base import (
    PLUGIN_KIND_DISPLAY_ORDER,
    Plugin,
    PluginKind,
    PluginManifest,
    SettingsScope,
)
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugin.manager import PluginManager, PluginRecord, PluginState

__all__ = [
    "PLUGIN_KIND_DISPLAY_ORDER",
    "Plugin",
    "PluginContext",
    "PluginKind",
    "PluginManager",
    "PluginManifest",
    "PluginRecord",
    "PluginState",
    "SettingsScope",
]
