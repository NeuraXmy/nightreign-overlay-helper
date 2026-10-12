"""Plugin system public API."""

from nightreign_overlay.plugin.base import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugin.manager import PluginManager, PluginRecord, PluginState

__all__ = [
    "Plugin",
    "PluginContext",
    "PluginKind",
    "PluginManager",
    "PluginManifest",
    "PluginRecord",
    "PluginState",
]
