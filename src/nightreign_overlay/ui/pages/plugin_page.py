"""Per plugin page: header with status / enable switch, plus "Settings" and "Tutorial" tabs.

The "Settings" tab carries a page-level reset button that restores the plugin's defaults after confirmation.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    IconWidget,
    ScrollArea,
    SegmentedWidget,
    TitleLabel,
)

from nightreign_overlay.core.i18n import tr
from nightreign_overlay.core.log import get_logger
from nightreign_overlay.plugin import PluginManager, PluginRecord
from nightreign_overlay.ui.components import create_reset_button
from nightreign_overlay.ui.components.plugin_widgets import PluginSwitch
from nightreign_overlay.ui.plugin_actions import state_text
from nightreign_overlay.ui.theme import fluent_icon
from nightreign_overlay.ui.tutorial import create_tutorial_browser

log = get_logger(__name__)

PAGE_MARGIN = 36


def plugin_page_name(plugin_id: str) -> str:
    return f"plugin-{plugin_id}"


class PluginPage(QWidget):
    def __init__(
        self, manager: PluginManager, record: PluginRecord, parent: QWidget | None = None, services=None
    ) -> None:
        super().__init__(parent)
        self.setObjectName(plugin_page_name(record.id))
        self._manager = manager
        self._record = record
        self._services = services

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, 24, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(16)
        layout.addLayout(self._create_header())

        self.segmented = SegmentedWidget(self)
        self.stack = QStackedWidget(self)
        self.resetButton: QWidget | None = None
        settings = self._create_settings()
        self._add_tab("settings", tr("plugin_page.tab.settings"), settings)
        self._add_tab("tutorial", tr("plugin_page.tab.tutorial"), self._create_tutorial())
        self.segmented.setCurrentItem("settings")
        tabs = QHBoxLayout()
        tabs.addWidget(self.segmented, 0, Qt.AlignmentFlag.AlignLeft)
        tabs.addStretch(1)
        if self.resetButton is not None:
            reset = self.resetButton
            tabs.addWidget(reset)
            # The reset only concerns the settings tab, so it is hidden while another tab is shown.
            self.stack.currentChanged.connect(
                lambda _index: reset.setVisible(self.stack.currentWidget() is settings)
            )
        layout.addLayout(tabs)
        layout.addWidget(self.stack, 1)

        self._update_state()
        manager.stateChanged.connect(self._update_state)

    @property
    def plugin_id(self) -> str:
        return self._record.id

    def _create_header(self) -> QHBoxLayout:
        icon = IconWidget(fluent_icon(self._record.manifest.icon), self)
        icon.setFixedSize(40, 40)
        title = TitleLabel(self._manager.display_name(self._record.id), self)
        description = BodyLabel(self._manager.description(self._record.id), self)
        description.setWordWrap(True)
        self.stateLabel = CaptionLabel(self)
        self.stateLabel.setTextColor(QColor(96, 96, 96), QColor(160, 160, 160))
        self.switch = PluginSwitch(self._manager, self._record.id, self)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        text_layout.addWidget(title)
        text_layout.addWidget(description)
        text_layout.addWidget(self.stateLabel)

        header = QHBoxLayout()
        header.setSpacing(20)
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(text_layout, 1)
        header.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignTop)
        return header

    def _add_tab(self, route_key: str, text: str, widget: QWidget) -> None:
        widget.setObjectName(f"{self.objectName()}-{route_key}")
        self.stack.addWidget(widget)
        self.segmented.addItem(route_key, text, lambda: self.stack.setCurrentWidget(widget))

    def _create_settings(self) -> QWidget:
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content: QWidget | None = None
        plugin = self._record.plugin
        if plugin is not None:
            try:
                content = plugin.create_settings_widget(scroll)
            except Exception:
                log.exception("Plugin %s failed to create its settings widget", self._record.id)
        if plugin is None or content is None:
            content = self._placeholder(tr("plugin_page.no_settings"), scroll)
        else:
            self.resetButton = create_reset_button(
                plugin.reset_settings, content, tr("settings_reset.plugin_content"), self
            )
        scroll.setWidget(content)
        # Must run after ``setWidget`` so the content widget is made transparent as well.
        scroll.enableTransparentBackground()
        return scroll

    def _create_tutorial(self) -> QWidget:
        path = self._record.plugin.ctx.tutorial_file() if self._record.plugin is not None else None
        if path is None:
            return self._placeholder(tr("plugin_page.no_tutorial"), self)
        from nightreign_overlay.core.services import ServiceRegistry

        return create_tutorial_browser(self._services or ServiceRegistry(self), path, self)

    @staticmethod
    def _placeholder(text: str, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        label = BodyLabel(text, widget)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(widget)
        layout.addWidget(label, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.setContentsMargins(0, 24, 0, 0)
        return widget

    def _update_state(self, _changed_id: str = "") -> None:
        self.stateLabel.setText(state_text(self._manager, self._record))
