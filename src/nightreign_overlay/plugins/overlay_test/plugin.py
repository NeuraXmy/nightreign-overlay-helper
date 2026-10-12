from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, PushSettingCard

from nightreign_overlay.core.game_window import GameForegroundChanged
from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.overlay_test.api import OverlayTestApi
from nightreign_overlay.plugins.overlay_test.config import OverlayTestConfig
from nightreign_overlay.plugins.overlay_test.overlay import OverlayTestWindow
from nightreign_overlay.ui.components import (
    ConfigColorCard,
    ConfigRangeCard,
    ConfigSwitchCard,
    OverlaySettingSection,
    SettingSection,
    SettingsPanel,
)
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayManager


class _OverlayTestService(OverlayTestApi):
    def __init__(self, window: OverlayTestWindow) -> None:
        self._window = window

    def restart_countdown(self) -> None:
        self._window.restart_countdown()


class OverlayTestPlugin(Plugin):
    manifest = PluginManifest(
        id="overlay_test",
        kind=PluginKind.DEBUG,
        icon="DEVELOPER_TOOLS",
        order=0,
    )

    def on_load(self) -> None:
        self.config = self.ctx.config(OverlayTestConfig)
        self.overlay_config = self.ctx.config(OverlayConfig, "overlay")
        self._window: OverlayTestWindow | None = None

    def on_activate(self) -> None:
        window = OverlayTestWindow(
            self.ctx.services.require(OverlayManager),
            self.overlay_config,
            self.config,
            self.ctx.tr,
        )
        self._window = window
        self.ctx.on_cleanup(window.dispose)
        self.ctx.provide(OverlayTestApi, _OverlayTestService(window))
        self.ctx.subscribe(GameForegroundChanged, self._on_game_foreground_changed)
        window.show_overlay()

    def on_deactivate(self) -> None:
        self._window = None

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        tr = self.ctx.tr
        panel = SettingsPanel(parent)
        panel.addSection(OverlaySettingSection(self.overlay_config))

        restart_card = PushSettingCard(
            tr("settings.restart.button"),
            FluentIcon.PLAY,
            tr("settings.restart.title"),
            tr("settings.restart.content"),
        )
        restart_card.clicked.connect(self._restart_countdown)
        content = SettingSection(tr("settings.content.title"))
        content.addCards(
            ConfigRangeCard(
                self.config.cycle_seconds,
                FluentIcon.STOP_WATCH,
                tr("settings.cycle_seconds.title"),
                tr("settings.cycle_seconds.content"),
                formatter=lambda value: tr("settings.cycle_seconds.value", seconds=value),
            ),
            ConfigColorCard(
                self.config.accent_color,
                FluentIcon.PALETTE,
                tr("settings.accent_color.title"),
                tr("settings.accent_color.content"),
            ),
            ConfigSwitchCard(
                self.config.show_background,
                FluentIcon.BACKGROUND_FILL,
                tr("settings.show_background.title"),
                tr("settings.show_background.content"),
            ),
            restart_card,
        )
        panel.addSection(content)
        return panel

    def _restart_countdown(self) -> None:
        # Goes through the service registry on purpose, exactly like another plugin would.
        service = self.ctx.services.get(OverlayTestApi)
        if service is not None:
            service.restart_countdown()

    def _on_game_foreground_changed(self, event: GameForegroundChanged) -> None:
        self.ctx.log.debug("Game foreground changed: %s", event.foreground)
        if self._window is not None:
            self._window.update()
