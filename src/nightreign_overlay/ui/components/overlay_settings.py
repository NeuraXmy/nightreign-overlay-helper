"""Standard settings for an :class:`OverlayConfig`, reusable by every overlay plugin."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.core.i18n import tr
from nightreign_overlay.ui.components.page import SettingSection
from nightreign_overlay.ui.components.setting_cards import (
    ConfigChoiceCard,
    ConfigRangeCard,
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
        include_horizontal_reset: bool = True,
    ) -> None:
        super().__init__(title or tr("overlay_settings.title"), parent)
        buttons = [(tr("overlay_settings.reset_position.reset"), config.reset_position)]
        if include_horizontal_reset:
            buttons.append(
                (tr("overlay_settings.reset_position.horizontal"), config.reset_horizontal_position)
            )
        reset_card = MultiButtonSettingCard(
            buttons,
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
            reset_card,
        )
