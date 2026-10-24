"""Frequently asked questions, with the same Markdown support as plugin tutorials."""

from PyQt6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import TitleLabel

from nightreign_overlay.core.i18n import tr, translator
from nightreign_overlay.core.paths import resource_path
from nightreign_overlay.ui.tutorial import create_tutorial_browser


class FaqPage(QWidget):
    def __init__(self, parent: QWidget | None = None, services=None) -> None:
        super().__init__(parent)
        self.setObjectName("faqPage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 36)
        layout.setSpacing(16)
        layout.addWidget(TitleLabel(tr("nav.faq"), self))

        path = translator().localized_file(resource_path("faq"), ".md")
        from nightreign_overlay.core.services import ServiceRegistry

        self.browser = (
            create_tutorial_browser(services or ServiceRegistry(self), path, self) if path else QWidget(self)
        )
        layout.addWidget(self.browser, 1)
