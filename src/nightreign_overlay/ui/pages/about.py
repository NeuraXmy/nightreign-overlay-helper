"""About page: version, links and acknowledgements."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, HyperlinkCard, PushSettingCard, SettingCard

from nightreign_overlay.core.i18n import tr
from nightreign_overlay.meta import APP_NAME, APP_VERSION, REPO_URL
from nightreign_overlay.ui.components import ScrollPage, SettingSection
from nightreign_overlay.ui.components.diagnostic_export import DiagnosticExportDialog
from nightreign_overlay.ui.components.licenses import LicensesDialog
from nightreign_overlay.ui.pages.home import Banner

#: (translation key, display name, url)
CREDITS = (
    ("fuwish", "Fuwish", "https://github.com/Fuwishx"),
    ("quexuan", "雀煊", "https://space.bilibili.com/391379672"),
    ("steam_p2p_info", "SteamP2PInfo", "https://github.com/tremwil/SteamP2PInfo"),
    ("fluent_widgets", "PyQt-Fluent-Widgets", "https://github.com/zhiyiYo/PyQt-Fluent-Widgets"),
    ("pyqt6", "PyQt6", "https://www.riverbankcomputing.com/software/pyqt/"),
)


class AboutPage(ScrollPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("aboutPage", parent=parent)
        self.addWidget(Banner(self.view))

        project = SettingSection(tr("about.project.title"), self.view)
        project.addCards(
            HyperlinkCard(
                REPO_URL,
                tr("about.project.repo_button"),
                FluentIcon.GITHUB,
                APP_NAME,
                tr("about.project.repo_content", version=APP_VERSION),
            ),
            self._feedback_card(),
            self._licenses_card(),
            SettingCard(
                FluentIcon.INFO,
                tr("about.security.title"),
                tr("about.security.content"),
            ),
        )
        self.addWidget(project)

        credits = SettingSection(tr("about.credits.title"), self.view)
        for key, name, url in CREDITS:
            credits.addCard(
                HyperlinkCard(
                    url, tr("about.credits.visit"), FluentIcon.HEART, name, tr(f"about.credits.{key}")
                )
            )
        self.addWidget(credits)

    def _licenses_card(self) -> PushSettingCard:
        card = PushSettingCard(
            tr("about.licenses.open"),
            FluentIcon.INFO,
            tr("about.licenses.title"),
            tr("about.licenses.content"),
        )
        card.clicked.connect(self._show_licenses)
        return card

    def _show_licenses(self) -> None:
        dialog = LicensesDialog(self.window())
        dialog.exec()
        dialog.deleteLater()

    def _feedback_card(self) -> PushSettingCard:
        card = PushSettingCard(
            tr("settings.diagnostic_export.button"),
            FluentIcon.FEEDBACK,
            tr("settings.diagnostic_export.title"),
            tr("settings.diagnostic_export.content"),
        )
        card.clicked.connect(self._export_diagnostics)
        return card

    def _export_diagnostics(self) -> None:
        dialog = DiagnosticExportDialog(self.window())
        dialog.exec()
        dialog.deleteLater()
