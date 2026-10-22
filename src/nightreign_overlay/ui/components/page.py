"""Page scaffolding: scrollable pages and titled groups of setting cards."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, ScrollArea, SettingCard, StrongBodyLabel, TitleLabel


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
        if isinstance(card, SettingCard):
            # Fluent cards default to a single-line description and a fixed height.
            # Let the text column use the space left by the controls and grow vertically.
            card.contentLabel.setWordWrap(True)
            policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            policy.setHeightForWidth(True)
            card.contentLabel.setSizePolicy(policy)
            card.vBoxLayout.setAlignment(card.contentLabel, Qt.AlignmentFlag(0))
            card.vBoxLayout.setAlignment(Qt.AlignmentFlag(0))
            card.hBoxLayout.setAlignment(Qt.AlignmentFlag(0))
            card.hBoxLayout.setStretch(2, 1)
            card.hBoxLayout.setStretch(4, 0)
            card.hBoxLayout.setContentsMargins(16, 12, 0, 12)
            card.setMinimumHeight(70 if card.contentLabel.text() else 50)
            card.setMaximumHeight(16777215)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.cardLayout.addWidget(card)
        return card

    def addCards(self, *cards: QWidget) -> None:
        for card in cards:
            self.addCard(card)


class SelectableSettingContainer(QFrame):
    """Show one named collection of ordinary setting widgets at a time."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("selectableSettingContainer")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame#selectableSettingContainer {"
            "border: 1px solid rgba(128, 128, 128, 110);"
            "border-radius: 8px;"
            "background-color: rgba(128, 128, 128, 16);"
            "}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.titleLabel = StrongBodyLabel(title, self)
        self.selector = ComboBox(self)
        self.selector.setMinimumWidth(180)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.titleLabel)
        header.addStretch(1)
        header.addWidget(self.selector)
        self.stack = QStackedWidget(self)
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.stack)
        self.selector.currentIndexChanged.connect(self._select_option)

    def addOption(self, label: str, *widgets: QWidget) -> QWidget:
        """Add a collection of existing widgets without changing their own config bindings."""
        page = QWidget(self.stack)
        page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        content = QVBoxLayout(page)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(4)
        for widget in widgets:
            widget.setParent(page)
            if isinstance(widget, SettingCard):
                widget.contentLabel.setWordWrap(True)
                policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                policy.setHeightForWidth(True)
                widget.contentLabel.setSizePolicy(policy)
                widget.vBoxLayout.setAlignment(widget.contentLabel, Qt.AlignmentFlag(0))
                widget.vBoxLayout.setAlignment(Qt.AlignmentFlag(0))
                widget.hBoxLayout.setAlignment(Qt.AlignmentFlag(0))
                widget.hBoxLayout.setStretch(2, 1)
                widget.hBoxLayout.setStretch(4, 0)
                widget.hBoxLayout.setContentsMargins(16, 12, 0, 12)
                widget.setMinimumHeight(70 if widget.contentLabel.text() else 50)
                widget.setMaximumHeight(16777215)
                widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            content.addWidget(widget)
        self.stack.addWidget(page)
        self.selector.addItem(label)
        if self.stack.count() == 1:
            self.stack.setCurrentIndex(0)
        self._adjust_height()
        return page

    def _select_option(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self._adjust_height()

    def _adjust_height(self) -> None:
        page = self.stack.currentWidget()
        if page is not None:
            page.adjustSize()
            self.stack.setMinimumHeight(page.sizeHint().height())
            page.updateGeometry()
        self.stack.updateGeometry()
        self.updateGeometry()
        ancestor = self
        while ancestor is not None:
            if layout := ancestor.layout():
                layout.activate()
            ancestor.updateGeometry()
            ancestor = ancestor.parentWidget()


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
