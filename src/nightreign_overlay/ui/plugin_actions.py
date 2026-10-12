"""User facing plugin operations shared by the home page and the plugin pages."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from qfluentwidgets import InfoBar, InfoBarPosition

from nightreign_overlay.core.i18n import tr
from nightreign_overlay.plugin import PluginManager, PluginRecord, PluginState

INFOBAR_DURATION_MS = 4000


def state_text(manager: PluginManager, record: PluginRecord) -> str:
    """Short human readable status of a plugin."""
    if record.state == PluginState.ACTIVE:
        return tr("plugin.state.active")
    if record.state == PluginState.FAILED:
        return tr("plugin.state.failed", error=record.error)
    if record.state == PluginState.UNAVAILABLE:
        if record.circular:
            return tr("plugin.state.circular")
        missing = ", ".join(record.missing) or ", ".join(
            manager.display_name(r) for r in record.manifest.requires if not _available(manager, r)
        )
        return tr("plugin.state.unavailable", plugins=missing)
    return tr("plugin.state.inactive")


def set_plugin_enabled(manager: PluginManager, plugin_id: str, enabled: bool, parent: QWidget) -> None:
    """Toggle a plugin and report cascading changes or failures with an info bar."""
    affected = manager.set_enabled(plugin_id, enabled)
    window = parent.window()
    record = manager.get(plugin_id)
    assert record is not None

    if enabled and record.state != PluginState.ACTIVE:
        InfoBar.error(
            manager.display_name(plugin_id),
            state_text(manager, record),
            duration=INFOBAR_DURATION_MS,
            position=InfoBarPosition.TOP,
            parent=window,
        )
    elif affected:
        names = ", ".join(manager.display_name(p) for p in affected)
        key = "plugin.cascade.enabled" if enabled else "plugin.cascade.disabled"
        InfoBar.info(
            manager.display_name(plugin_id),
            tr(key, plugins=names),
            duration=INFOBAR_DURATION_MS,
            position=InfoBarPosition.TOP,
            parent=window,
        )


def _available(manager: PluginManager, plugin_id: str) -> bool:
    record = manager.get(plugin_id)
    return record is not None and record.state != PluginState.UNAVAILABLE
