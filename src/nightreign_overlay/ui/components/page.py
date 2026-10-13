"""Page scaffolding: scrollable pages and titled groups of setting cards."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import ScrollArea, StrongBodyLabel, TitleLabel


class ScrollPage(ScrollArea):
    """A vertically scrolling page; use :meth:`addWidget` to append content.

    With a title, page-level actions can be appended to the right of it through ``headerLayout``.
    """

    def __init__(self, object_name: str, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.view = QWidget(self)
        self.contentLayout = QVBoxLayout(self.view)
        self.contentLayout.setContentsMargins(36, 24, 36, 36)
        self.contentLayout.setSpacing(24)
        self.contentLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        if title:
            self.headerLayout = QHBoxLayout()
            self.headerLayout.addWidget(TitleLabel(title, self.view))
            self.headerLayout.addStretch(1)
            self.contentLayout.addLayout(self.headerLayout)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.enableTransparentBackground()

    def addWidget(self, widget: QWidget, stretch: int = 0) -> None:
        self.contentLayout.addWidget(widget, stretch)


class SettingSection(QWidget):
    """A caption followed by a vertical stack of setting cards."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.titleLabel = StrongBodyLabel(title, self)
        self.cardLayout = QVBoxLayout()
        self.cardLayout.setSpacing(4)
        self.cardLayout.setContentsMargins(0, 0, 0, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.titleLabel)
        layout.addLayout(self.cardLayout)

    def addCard(self, card: QWidget) -> QWidget:
        card.setParent(self)
        self.cardLayout.addWidget(card)
        return card

    def addCards(self, *cards: QWidget) -> None:
        for card in cards:
            self.addCard(card)


class SettingsPanel(QWidget):
    """Top aligned stack of :class:`SettingSection` objects; the usual root of a plugin's settings tab."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sectionLayout = QVBoxLayout(self)
        # Leave room on the right for the scroll bar of the hosting page.
        self.sectionLayout.setContentsMargins(0, 0, 12, 12)
        self.sectionLayout.setSpacing(24)
        self.sectionLayout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def addSection(self, section: QWidget) -> QWidget:
        section.setParent(self)
        self.sectionLayout.addWidget(section)
        return section
