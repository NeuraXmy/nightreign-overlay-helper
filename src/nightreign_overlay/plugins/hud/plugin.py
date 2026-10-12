"""Lifecycle wrapper and service facade for :mod:`nightreign_overlay.plugins.hud`."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest, SettingsScope
from nightreign_overlay.plugins.hud.api import HudApi
from nightreign_overlay.plugins.hud.config import HudConfig
from nightreign_overlay.plugins.hud.overlay import HudOverlay
from nightreign_overlay.ui.components import (
    ConfigChoiceCard,
    ConfigRangeCard,
    OverlaySettingSection,
    SettingSection,
    SettingsPanel,
)
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
        order=30,
    )

    def on_load(self) -> None:
        self.config = self.ctx.config(HudConfig)
        self.overlay_config = self.ctx.config(OverlayConfig, "overlay")
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
        panel.addSection(OverlaySettingSection(self.overlay_config))
        section = SettingSection(self.ctx.tr("settings.layout.title"))
        section.addCards(
            ConfigChoiceCard(
                self.config.direction,
                [
                    ("vertical", self.ctx.tr("settings.direction.vertical")),
                    ("horizontal", self.ctx.tr("settings.direction.horizontal")),
                ],
                FluentIcon.TILES,
                self.ctx.tr("settings.direction.title"),
                self.ctx.tr("settings.direction.content"),
            ),
            ConfigRangeCard(
                self.config.spacing,
                FluentIcon.ALIGNMENT,
                self.ctx.tr("settings.spacing.title"),
                self.ctx.tr("settings.spacing.content"),
                formatter=lambda value: self.ctx.tr("settings.spacing.value", pixels=value),
            ),
        )
        panel.addSection(section)
        return panel
