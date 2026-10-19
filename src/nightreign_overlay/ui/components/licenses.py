"""Offline viewer for the application's license texts and source instructions."""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, PushButton

from nightreign_overlay.core.i18n import tr
from nightreign_overlay.core.paths import resource_path
from nightreign_overlay.ui.markdown import MarkdownTextBrowser, configure_markdown_browser

DOCUMENTS = (
    ("THIRD-PARTY-NOTICES.md", "about.licenses.notices"),
    ("SOURCE.md", "about.licenses.source"),
    ("AGPL-3.0.txt", "AGPL-3.0"),
    ("PyQt6-Fluent-Widgets-LICENSE.txt", "PyQt6-Fluent-Widgets — GPLv3"),
    ("PyQt6-LICENSE.txt", "PyQt6 — GPLv3"),
    ("SteamP2PInfo-LICENSE.txt", "SteamP2PInfo — MIT"),
)


class LicensesDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("about.licenses.title"))
        self.resize(840, 640)
        layout = QVBoxLayout(self)
        self.selector = ComboBox(self)
        for _, label in DOCUMENTS:
            self.selector.addItem(tr(label) if label.startswith("about.") else label)
        layout.addWidget(self.selector)
        self.browser = MarkdownTextBrowser(self)
        self.browser.setOpenExternalLinks(True)
        configure_markdown_browser(self.browser)
        layout.addWidget(self.browser, 1)
        close = PushButton(tr("about.licenses.close"), self)
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self.selector.currentIndexChanged.connect(self._show_document)
        self._show_document(0)

    def _show_document(self, index: int) -> None:
        filename = DOCUMENTS[index][0]
        text = resource_path("licenses", filename).read_text(encoding="utf-8")
        if filename.endswith(".md"):
            self.browser.setMarkdown(text)
        else:
            self.browser.setPlainText(text)
