"""Standard settings for an :class:`OverlayConfig`, reusable by every overlay plugin."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.core.i18n import tr
from nightreign_overlay.ui.components.page import SettingSection
from nightreign_overlay.ui.components.setting_cards import (
    ConfigChoiceCard,
    ConfigRangeCard,
    ConfigSwitchCard,
    MultiButtonSettingCard,
)
from nightreign_overlay.ui.overlay import OverlayConfig


class OverlaySettingSection(SettingSection):
    def __init__(
        self,
        config: OverlayConfig,
        title: str | None = None,
        parent: QWidget | None = None,
        leading_cards: tuple[QWidget, ...] = (),
    ) -> None:
        super().__init__(title or tr("overlay_settings.title"), parent)
        reset_card = MultiButtonSettingCard(
            [
                (tr("overlay_settings.reset_position.reset"), config.position.reset),
                (
                    tr("overlay_settings.reset_position.horizontal"),
                    lambda: _reset_horizontal_position(config),
                ),
            ],
            FluentIcon.SYNC,
            tr("overlay_settings.reset_position.title"),
            tr("overlay_settings.reset_position.content"),
        )
        self.addCards(
            *leading_cards,
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
            ConfigChoiceCard(
                config.input_mode,
                [
                    ("normal", tr("overlay_settings.input_mode.normal")),
                    ("locked", tr("overlay_settings.input_mode.locked")),
                    ("passthrough", tr("overlay_settings.input_mode.passthrough")),
                ],
                FluentIcon.FILTER,
                tr("overlay_settings.input_mode.title"),
                tr("overlay_settings.input_mode.content"),
            ),
            ConfigSwitchCard(
                config.only_when_game_foreground,
                FluentIcon.GAME,
                tr("overlay_settings.only_when_game_foreground.title"),
                tr("overlay_settings.only_when_game_foreground.content"),
            ),
            reset_card,
        )


def _reset_horizontal_position(config: OverlayConfig) -> None:
    position = config.position.value
    config.position.set([None, position[1] if position is not None else None])
