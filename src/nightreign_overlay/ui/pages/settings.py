"""General application settings."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, InfoBar, InfoBarPosition, PushButton, PushSettingCard

from nightreign_overlay.core.app_config import OVERLAY_MODES, THEMES, AppConfig
from nightreign_overlay.core.i18n import language_names, tr
from nightreign_overlay.core.log import LOG_LEVELS, get_logger, set_log_level
from nightreign_overlay.core.paths import log_dir, user_data_dir
from nightreign_overlay.plugin import Plugin, PluginManager, SettingsScope
from nightreign_overlay.ui.components import (
    ConfigChoiceCard,
    ConfigColorCard,
    ConfigSwitchCard,
    ScrollPage,
    SettingSection,
    create_reset_button,
)
from nightreign_overlay.ui.components.diagnostic_export import DiagnosticExportDialog

log = get_logger(__name__)


class SettingsPage(ScrollPage):
    #: The user asked to restart the application (e.g. to apply a new language).
    restartRequested = pyqtSignal()

    def __init__(self, config: AppConfig, plugins: PluginManager, parent: QWidget | None = None) -> None:
        super().__init__("settingsPage", tr("settings.title"), parent)
        self._config = config
        self._plugins: list[Plugin] = []
        self._init_general()
        self._init_plugin_settings(plugins)
        self._init_advanced()
        self.resetButton = create_reset_button(
            self._reset_settings, self.view, tr("settings_reset.general_content"), self.view
        )
        self.headerLayout.addWidget(self.resetButton)

        config.language.valueChanged.connect(self._on_language_changed)
        config.log_level.valueChanged.connect(set_log_level)

    def _init_general(self) -> None:
        """Group appearance, overlay presentation, and startup behavior together."""
        section = SettingSection(tr("settings.general.title"), self.view)
        languages = [("auto", tr("settings.language.auto")), *language_names().items()]
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
            ConfigChoiceCard(
                self._config.overlay_mode,
                [(mode, tr(f"settings.overlay_mode.{mode}")) for mode in OVERLAY_MODES],
                FluentIcon.FIT_PAGE,
                tr("settings.overlay_mode.title"),
                tr("settings.overlay_mode.content"),
            ),
            ConfigSwitchCard(
                self._config.only_when_game_foreground,
                FluentIcon.GAME,
                tr("settings.only_when_game_foreground.title"),
                tr("settings.only_when_game_foreground.content"),
            ),
            ConfigSwitchCard(
                self._config.start_minimized,
                FluentIcon.HIDE,
                tr("settings.start_minimized.title"),
                tr("settings.start_minimized.content"),
            ),
        )
        self.addWidget(section)

    def _init_plugin_settings(self, plugins: PluginManager) -> None:
        """Embed general-scope plugin settings without creating extra navigation pages."""
        records = sorted(plugins.records(), key=lambda record: record.manifest.order)
        for record in records:
            if record.manifest.settings_scope != SettingsScope.GENERAL or record.plugin is None:
                continue
            try:
                content = record.plugin.create_settings_widget(self.view)
            except Exception:
                log.exception("Plugin %s failed to create its general settings widget", record.id)
                continue
            if content is not None:
                self._plugins.append(record.plugin)
                self.addWidget(content)

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
        self.diagnosticExportCard = PushSettingCard(
            tr("settings.diagnostic_export.button"),
            FluentIcon.ZIP_FOLDER,
            tr("settings.diagnostic_export.title"),
            tr("settings.diagnostic_export.content"),
        )
        self.diagnosticExportCard.clicked.connect(self._export_diagnostics)
        section.addCards(
            ConfigChoiceCard(
                self._config.log_level,
                [(level, level) for level in LOG_LEVELS],
                FluentIcon.DEVELOPER_TOOLS,
                tr("settings.log_level.title"),
                tr("settings.log_level.content"),
            ),
            ConfigSwitchCard(
                self._config.debug_images_enabled,
                FluentIcon.DEVELOPER_TOOLS,
                tr("settings.debug_images.title"),
                tr("settings.debug_images.content"),
            ),
            data_card,
            log_card,
            self.diagnosticExportCard,
        )
        self.addWidget(section)

    def _export_diagnostics(self) -> None:
        dialog = DiagnosticExportDialog(self.window())
        dialog.exec()
        dialog.deleteLater()

    def _reset_settings(self) -> None:
        for item in self._config.items().values():
            # Internal bookkeeping, not a setting shown on this page.
            if item is not self._config.tray_hint_shown:
                item.reset()
        for plugin in self._plugins:
            try:
                plugin.reset_settings()
            except Exception:
                log.exception("Plugin %s failed to reset its general settings", plugin.id)
        log.info("General settings reset to defaults.")

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
