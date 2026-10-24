"""Home page: banner, runtime status and an overview of all plugins."""

from __future__ import annotations

from contextlib import suppress

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPaintEvent
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    FluentIconBase,
    IconWidget,
    SimpleCardWidget,
    StrongBodyLabel,
    qconfig,
    themeColor,
)

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.game_window import GameWindowMonitor
from nightreign_overlay.core.i18n import tr
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.meta import APP_NAME, APP_VERSION
from nightreign_overlay.plugin import (
    PLUGIN_KIND_DISPLAY_ORDER,
    PluginManager,
    PluginRecord,
    PluginState,
    SettingsScope,
)
from nightreign_overlay.plugins.capture.api import CaptureApi
from nightreign_overlay.ui.components import ScrollPage, SettingSection
from nightreign_overlay.ui.components.plugin_widgets import PluginSwitch
from nightreign_overlay.ui.overlay import OverlayManager
from nightreign_overlay.ui.plugin_actions import state_text
from nightreign_overlay.ui.theme import app_icon, fluent_icon

BANNER_HEIGHT = round(168 * 0.6)


class Banner(QWidget):
    """Gradient header with the application name and version."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(BANNER_HEIGHT)
        qconfig.themeColorChanged.connect(self._on_theme_color_changed)

    def _on_theme_color_changed(self, _color: QColor) -> None:
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)

        accent = themeColor()
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, accent.darker(170))
        gradient.setColorAt(1, QColor(24, 24, 28))
        painter.fillPath(path, gradient)

        icon_size = 72
        icon_rect = QRectF(32, (rect.height() - icon_size) / 2, icon_size, icon_size)
        app_icon().paint(painter, icon_rect.toRect())

        text_left = icon_rect.right() + 24
        text_top = (rect.height() - 80) / 2
        painter.setPen(QColor(255, 255, 255))
        title_font = QFont(self.font())
        title_font.setPixelSize(28)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.drawText(
            QRectF(text_left, text_top, rect.width() - text_left, 36), Qt.AlignmentFlag.AlignVCenter, APP_NAME
        )

        body_font = QFont(self.font())
        body_font.setPixelSize(14)
        painter.setFont(body_font)
        painter.setPen(QColor(255, 255, 255, 200))
        painter.drawText(
            QRectF(text_left, text_top + 36, rect.width() - text_left, 24),
            Qt.AlignmentFlag.AlignVCenter,
            tr("home.subtitle"),
        )
        painter.setPen(QColor(255, 255, 255, 150))
        painter.drawText(
            QRectF(text_left, text_top + 60, rect.width() - text_left, 20),
            Qt.AlignmentFlag.AlignVCenter,
            tr("home.version", version=APP_VERSION),
        )


class StatusCard(SimpleCardWidget):
    def __init__(self, icon: FluentIconBase, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(76)
        self.iconWidget = IconWidget(icon, self)
        self.iconWidget.setFixedSize(28, 28)
        self.titleLabel = CaptionLabel(title, self)
        self.valueLabel = StrongBodyLabel(self)
        self.valueLabel.setWordWrap(True)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.addWidget(self.titleLabel)
        text_layout.addWidget(self.valueLabel)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(16)
        layout.addWidget(self.iconWidget)
        layout.addLayout(text_layout, 1)

    def setValue(self, text: str) -> None:
        self.valueLabel.setText(text)


class PluginCard(CardWidget):
    """Clickable plugin summary with an enable switch; clicking opens the plugin page."""

    def __init__(self, manager: PluginManager, record: PluginRecord, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._record = record
        self.setMinimumHeight(72)

        self.iconWidget = IconWidget(fluent_icon(record.manifest.icon), self)
        self.iconWidget.setFixedSize(24, 24)
        self.nameLabel = BodyLabel(manager.display_name(record.id), self)
        self.descriptionLabel = CaptionLabel(manager.description(record.id), self)
        self.descriptionLabel.setTextColor(QColor(96, 96, 96), QColor(206, 206, 206))
        self.stateLabel = CaptionLabel(self)
        self.switch = PluginSwitch(manager, record.id, self)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(0)
        text_layout.addWidget(self.nameLabel)
        text_layout.addWidget(self.descriptionLabel)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(16)
        layout.addWidget(self.iconWidget)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.stateLabel)
        layout.addSpacing(8)
        layout.addWidget(self.switch)

        self._update_state()
        manager.stateChanged.connect(self._update_state)

    @property
    def plugin_id(self) -> str:
        return self._record.id

    def _update_state(self, _changed_id: str = "") -> None:
        self.stateLabel.setText(state_text(self._manager, self._record))
        if self._record.state == PluginState.ACTIVE:
            self.stateLabel.setTextColor(themeColor(), themeColor())
        else:
            self.stateLabel.setTextColor(QColor(96, 96, 96), QColor(160, 160, 160))


class HomePage(ScrollPage):
    #: The user clicked a plugin card.
    pluginRequested = pyqtSignal(str)

    def __init__(
        self,
        app_config: AppConfig,
        plugins: PluginManager,
        overlays: OverlayManager,
        game_monitor: GameWindowMonitor,
        parent: QWidget | None = None,
        services: ServiceRegistry | None = None,
    ) -> None:
        super().__init__("homePage", parent=parent)
        self._app_config = app_config
        self._plugins = plugins
        self._overlays = overlays
        self._game_monitor = game_monitor
        self._services = services

        self.addWidget(Banner(self.view))
        self.hintLabel = BodyLabel(tr("home.first_use_hint"), self.view)
        self.hintLabel.setWordWrap(True)
        self.addWidget(self.hintLabel)
        self._init_status()
        self._init_plugins()

        self._update_game_status()
        self._update_capture_status()
        self._update_plugin_status()
        game_monitor.windowChanged.connect(self._update_game_status)
        if services is not None:
            services.serviceChanged.connect(self._on_service_changed)
            self._connect_capture_status()
        plugins.stateChanged.connect(self._update_plugin_status)

    def _init_status(self) -> None:
        section = SettingSection(tr("home.status.title"), self.view)
        self.gameCard = StatusCard(FluentIcon.GAME, tr("home.status.game"), section)
        self.overlayCard = StatusCard(FluentIcon.CAMERA, tr("home.status.capture"), section)
        self.pluginCard = StatusCard(FluentIcon.APPLICATION, tr("home.status.plugins"), section)

        grid = QGridLayout()
        grid.setSpacing(12)
        for column, card in enumerate((self.gameCard, self.overlayCard, self.pluginCard)):
            grid.addWidget(card, 0, column)
            grid.setColumnStretch(column, 1)
        section.cardLayout.addLayout(grid)
        self.addWidget(section)

    def _init_plugins(self) -> None:
        records = [
            record
            for record in self._plugins.records()
            if record.manifest.settings_scope == SettingsScope.PAGE
        ]
        if not records:
            section = SettingSection(tr("home.plugins.title"), self.view)
            hint = BodyLabel(tr("home.plugins.empty"), section)
            hint.setWordWrap(True)
            section.addCard(hint)
            self.addWidget(section)
            return

        for kind in PLUGIN_KIND_DISPLAY_ORDER:
            group = [
                record
                for record in records
                if record.manifest.kind == kind and record.manifest.settings_scope == SettingsScope.PAGE
            ]
            if not group:
                continue
            section = SettingSection(tr(f"plugin.kind.{kind.value}"), self.view)
            for record in group:
                card = PluginCard(self._plugins, record, section)
                card.clicked.connect(lambda plugin_id=record.id: self.pluginRequested.emit(plugin_id))
                section.addCard(card)
            self.addWidget(section)

    def _update_game_status(self, _window_open: bool = False) -> None:
        if not self._game_monitor.supported:
            text = tr("home.status.game_unsupported")
        elif self._game_monitor.is_window_open:
            text = tr("home.status.game_open")
        else:
            text = tr("home.status.game_closed")
        self.gameCard.setValue(text)

    def _on_service_changed(self, api: type) -> None:
        if api is CaptureApi:
            self._connect_capture_status()
            self._update_capture_status()

    def _connect_capture_status(self) -> None:
        service = self._services.get(CaptureApi) if self._services is not None else None
        if service is not None:
            plugin = self._plugins.get("capture")
            if plugin is not None and plugin.plugin is not None:
                with suppress(TypeError):
                    plugin.plugin.statusChanged.disconnect(self._update_capture_status)
                plugin.plugin.statusChanged.connect(self._update_capture_status)

    def _update_capture_status(self, _status: str = "") -> None:
        service = self._services.get(CaptureApi) if self._services is not None else None
        status = service.capture_status() if service is not None else "inactive"
        key = f"home.status.capture_{status}"
        text = tr(key)
        method = service.capture_method() if service is not None and status == "running" else None
        if method:
            text = tr("home.status.capture_running_method", method=method)
        self.overlayCard.setValue(text)

    def _update_plugin_status(self, _changed_id: str = "") -> None:
        records = [
            record
            for record in self._plugins.records()
            if record.manifest.settings_scope == SettingsScope.PAGE
        ]
        active = sum(record.state == PluginState.ACTIVE for record in records)
        self.pluginCard.setValue(tr("home.status.plugins_value", active=active, total=len(records)))
