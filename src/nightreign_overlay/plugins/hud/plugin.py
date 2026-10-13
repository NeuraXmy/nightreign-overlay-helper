"""Lifecycle wrapper and service facade for :mod:`nightreign_overlay.plugins.hud`."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest, SettingsScope
from nightreign_overlay.plugins.hud.api import HudApi
from nightreign_overlay.plugins.hud.config import HudConfig
from nightreign_overlay.plugins.hud.overlay import HudOverlay
from nightreign_overlay.ui.components import ConfigSwitchCard, OverlaySettingSection, SettingsPanel
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayManager


class _HudService(HudApi):
    def __init__(self, overlay: HudOverlay) -> None:
        self._overlay = overlay

    def add_widget(self, owner: str, widget: QWidget, order: int = 100) -> str:
        return self._overlay.add_widget(owner, widget, order)

    def remove_widget(self, token: str) -> None:
        self._overlay.remove_widget(token)

    def remove_owner(self, owner: str) -> None:
        self._overlay.remove_owner(owner)


class HudPlugin(Plugin):
    manifest = PluginManifest(
        id="hud",
        kind=PluginKind.INFRASTRUCTURE,
        icon="LAYOUT",
        settings_scope=SettingsScope.GENERAL,
        order=-10,
    )

    def on_load(self) -> None:
        self.config = self.ctx.config(HudConfig)
        self.overlay_config = self.ctx.config(OverlayConfig, "overlay")
        self.config.hide_text.valueChanged.connect(
            lambda value: self.ctx.log.info("Overlay hide text set to %s", value)
        )
        self._overlay: HudOverlay | None = None

    def on_activate(self) -> None:
        overlay = HudOverlay(
            self.ctx.services.require(OverlayManager),
            self.overlay_config,
            self.config,
            self.ctx.tr("plugin.name"),
        )
        self._overlay = overlay
        self.ctx.provide(HudApi, _HudService(overlay))
        self.ctx.on_cleanup(overlay.dispose)
        overlay.show_overlay()

    def on_deactivate(self) -> None:
        self._overlay = None

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        panel = SettingsPanel(parent)
        enabled_card = ConfigSwitchCard(
            self.config.enabled,
            FluentIcon.VIEW,
            self.ctx.tr("settings.enabled.title"),
            self.ctx.tr("settings.enabled.content"),
        )
        hide_text_card = ConfigSwitchCard(
            self.config.hide_text,
            FluentIcon.FONT,
            self.ctx.tr("settings.hide_text.title"),
            self.ctx.tr("settings.hide_text.content"),
        )
        panel.addSection(
            OverlaySettingSection(self.overlay_config, leading_cards=(enabled_card, hide_text_card))
        )
        return panel
