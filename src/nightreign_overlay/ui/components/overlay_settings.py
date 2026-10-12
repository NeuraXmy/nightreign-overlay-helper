"""Standard settings for an :class:`OverlayConfig`, reusable by every overlay plugin."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, PushSettingCard

from nightreign_overlay.core.i18n import tr
from nightreign_overlay.ui.components.page import SettingSection
from nightreign_overlay.ui.components.setting_cards import ConfigRangeCard, ConfigSwitchCard
from nightreign_overlay.ui.overlay import OverlayConfig


class OverlaySettingSection(SettingSection):
    def __init__(
        self, config: OverlayConfig, title: str | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(title or tr("overlay_settings.title"), parent)
        reset_card = PushSettingCard(
            tr("overlay_settings.reset_position.button"),
            FluentIcon.SYNC,
            tr("overlay_settings.reset_position.title"),
            tr("overlay_settings.reset_position.content"),
        )
        reset_card.clicked.connect(config.position.reset)
        self.addCards(
            ConfigRangeCard(
                config.opacity,
                FluentIcon.TRANSPARENT,
                tr("overlay_settings.opacity.title"),
                tr("overlay_settings.opacity.content"),
                formatter=lambda value: f"{value}%",
            ),
            ConfigRangeCard(
                config.scale,
                FluentIcon.ZOOM,
                tr("overlay_settings.scale.title"),
                tr("overlay_settings.scale.content"),
                formatter=lambda value: f"{value}%",
            ),
            ConfigSwitchCard(
                config.click_through,
                FluentIcon.FILTER,
                tr("overlay_settings.click_through.title"),
                tr("overlay_settings.click_through.content"),
            ),
            ConfigSwitchCard(
                config.only_when_game_foreground,
                FluentIcon.GAME,
                tr("overlay_settings.only_when_game_foreground.title"),
                tr("overlay_settings.only_when_game_foreground.content"),
            ),
            reset_card,
        )
