"""Frequently asked questions, with the same Markdown support as plugin tutorials."""

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import TextBrowser, TitleLabel

from nightreign_overlay.core.i18n import tr, translator
from nightreign_overlay.core.paths import resource_path


class FaqPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("faqPage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 36)
        layout.setSpacing(16)
        layout.addWidget(TitleLabel(tr("nav.faq"), self))

        self.browser = TextBrowser(self)
        self.browser.setOpenExternalLinks(True)
        path = translator().localized_file(resource_path("faq"), ".md")
        if path is not None:
            # Loading the source also resolves images relative to the Markdown file.
            self.browser.setSource(QUrl.fromLocalFile(str(path)), QTextDocument.ResourceType.MarkdownResource)
        layout.addWidget(self.browser, 1)
