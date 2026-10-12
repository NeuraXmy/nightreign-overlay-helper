"""General application settings."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, InfoBar, InfoBarPosition, PushButton, PushSettingCard

from nightreign_overlay.core.app_config import OVERLAY_MODES, THEMES, AppConfig
from nightreign_overlay.core.i18n import LANGUAGES, tr
from nightreign_overlay.core.log import LOG_LEVELS, set_log_level
from nightreign_overlay.core.paths import log_dir, user_data_dir
from nightreign_overlay.ui.components import (
    ConfigChoiceCard,
    ConfigColorCard,
    ConfigSwitchCard,
    ScrollPage,
    SettingSection,
)


class SettingsPage(ScrollPage):
    #: The user asked to restart the application (e.g. to apply a new language).
    restartRequested = pyqtSignal()

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__("settingsPage", tr("settings.title"), parent)
        self._config = config
        self._init_appearance()
        self._init_overlay()
        self._init_behavior()
        self._init_advanced()

        config.language.valueChanged.connect(self._on_language_changed)
        config.log_level.valueChanged.connect(set_log_level)

    def _init_appearance(self) -> None:
        section = SettingSection(tr("settings.appearance.title"), self.view)
        languages = [("auto", tr("settings.language.auto")), *LANGUAGES.items()]
        section.addCards(
            ConfigChoiceCard(
                self._config.language,
                languages,
                FluentIcon.LANGUAGE,
                tr("settings.language.title"),
                tr("settings.language.content"),
            ),
            ConfigChoiceCard(
                self._config.theme,
                [(theme, tr(f"settings.theme.{theme}")) for theme in THEMES],
                FluentIcon.BRUSH,
                tr("settings.theme.title"),
                tr("settings.theme.content"),
            ),
            ConfigColorCard(
                self._config.theme_color,
                FluentIcon.PALETTE,
                tr("settings.theme_color.title"),
                tr("settings.theme_color.content"),
            ),
        )
        self.addWidget(section)

    def _init_overlay(self) -> None:
        section = SettingSection(tr("settings.overlay.title"), self.view)
        section.addCard(
            ConfigChoiceCard(
                self._config.overlay_mode,
                [(mode, tr(f"settings.overlay_mode.{mode}")) for mode in OVERLAY_MODES],
                FluentIcon.FIT_PAGE,
                tr("settings.overlay_mode.title"),
                tr("settings.overlay_mode.content"),
            )
        )
        self.addWidget(section)

    def _init_behavior(self) -> None:
        section = SettingSection(tr("settings.behavior.title"), self.view)
        section.addCards(
            ConfigSwitchCard(
                self._config.close_to_tray,
                FluentIcon.MINIMIZE,
                tr("settings.close_to_tray.title"),
                tr("settings.close_to_tray.content"),
            ),
            ConfigSwitchCard(
                self._config.start_minimized,
                FluentIcon.HIDE,
                tr("settings.start_minimized.title"),
                tr("settings.start_minimized.content"),
            ),
        )
        self.addWidget(section)

    def _init_advanced(self) -> None:
        section = SettingSection(tr("settings.advanced.title"), self.view)
        data_card = PushSettingCard(
            tr("settings.open"),
            FluentIcon.FOLDER,
            tr("settings.data_dir.title"),
            str(user_data_dir()),
        )
        data_card.clicked.connect(lambda: _open_directory(user_data_dir()))
        log_card = PushSettingCard(
            tr("settings.open"),
            FluentIcon.DOCUMENT,
            tr("settings.log_dir.title"),
            str(log_dir()),
        )
        log_card.clicked.connect(lambda: _open_directory(log_dir()))
        section.addCards(
            ConfigChoiceCard(
                self._config.log_level,
                [(level, level) for level in LOG_LEVELS],
                FluentIcon.DEVELOPER_TOOLS,
                tr("settings.log_level.title"),
                tr("settings.log_level.content"),
            ),
            data_card,
            log_card,
        )
        self.addWidget(section)

    def _on_language_changed(self, _language: str) -> None:
        bar = InfoBar.warning(
            tr("settings.restart.title"),
            tr("settings.restart.content"),
            duration=-1,
            position=InfoBarPosition.TOP,
            parent=self.window(),
        )
        button = PushButton(tr("settings.restart.button"), bar)
        button.clicked.connect(lambda: self.restartRequested.emit())
        bar.addWidget(button)


def _open_directory(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
