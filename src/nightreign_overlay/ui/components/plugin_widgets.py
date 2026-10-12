"""Widgets that reflect and control plugin state."""

from __future__ import annotations

from PyQt6.QtCore import QSignalBlocker
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import IndicatorPosition, SwitchButton

from nightreign_overlay.plugin import PluginManager, PluginState
from nightreign_overlay.ui.components.setting_cards import localize_switch
from nightreign_overlay.ui.plugin_actions import set_plugin_enabled


class PluginSwitch(SwitchButton):
    """Enable switch for one plugin, kept in sync with the manager (including cascaded changes)."""

    def __init__(self, manager: PluginManager, plugin_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, IndicatorPosition.RIGHT)
        localize_switch(self)
        self._manager = manager
        self._plugin_id = plugin_id
        self.sync()
        self.checkedChanged.connect(self._on_toggled)
        # Any state change may be a cascade affecting this plugin, so resync on all of them.
        manager.stateChanged.connect(self.sync)

    def sync(self, _changed_id: str = "") -> None:
        record = self._manager.get(self._plugin_id)
        assert record is not None
        with QSignalBlocker(self):
            self.setChecked(
                self._manager.is_enabled(self._plugin_id) and record.state != PluginState.UNAVAILABLE
            )
        self.setEnabled(record.state != PluginState.UNAVAILABLE)

    def _on_toggled(self, checked: bool) -> None:
        set_plugin_enabled(self._manager, self._plugin_id, checked, self)
        self.sync()
