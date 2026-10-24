"""Main window: navigation between home, plugin pages, settings and about."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QGuiApplication, QHideEvent, QShowEvent
from qfluentwidgets import FluentIcon, FluentWindow, NavigationItemPosition

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.game_window import GameWindowMonitor
from nightreign_overlay.core.i18n import tr
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.meta import APP_NAME
from nightreign_overlay.plugin import PLUGIN_KIND_DISPLAY_ORDER, PluginManager, SettingsScope
from nightreign_overlay.ui.overlay import OverlayManager
from nightreign_overlay.ui.pages import AboutPage, FaqPage, HomePage, PluginPage, SettingsPage
from nightreign_overlay.ui.theme import app_icon, fluent_icon

DEFAULT_SIZE = (1080, 760)
MINIMUM_WIDTH = 760


class MainWindow(FluentWindow):
    #: Closing or the tray toggle hid the window while the application continues running.
    hiddenToTray = pyqtSignal()
    #: An explicit action requested application exit.
    quitRequested = pyqtSignal()
    #: Whether the window is on screen (shown and not minimized); legacy "settings window opened".
    presenceChanged = pyqtSignal(bool)

    def __init__(
        self,
        config: AppConfig,
        plugins: PluginManager,
        overlays: OverlayManager,
        game_monitor: GameWindowMonitor,
        services: ServiceRegistry | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._quitting = False
        self._plugin_pages: dict[str, PluginPage] = {}
        self._services = services or ServiceRegistry(self)

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        # A normal window: not kept on top. Detection gating ignores the main window's presence.
        self.setMinimumWidth(MINIMUM_WIDTH)
        self.resize(*DEFAULT_SIZE)
        self._center_on_screen()

        self.homePage = HomePage(config, plugins, overlays, game_monitor, self)
        self.homePage.pluginRequested.connect(self.show_plugin)
        self.addSubInterface(self.homePage, FluentIcon.HOME, tr("nav.home"))
        self._init_plugin_pages(plugins)

        self.faqPage = FaqPage(self, self._services)
        self.settingsPage = SettingsPage(config, plugins, self)
        self.aboutPage = AboutPage(config, self)
        self.addSubInterface(self.faqPage, FluentIcon.HELP, tr("nav.faq"), NavigationItemPosition.BOTTOM)
        self.addSubInterface(
            self.settingsPage, FluentIcon.SETTING, tr("nav.settings"), NavigationItemPosition.BOTTOM
        )
        self.addSubInterface(self.aboutPage, FluentIcon.INFO, tr("nav.about"), NavigationItemPosition.BOTTOM)

    def _init_plugin_pages(self, plugins: PluginManager) -> None:
        records = plugins.records()
        for kind in PLUGIN_KIND_DISPLAY_ORDER:
            group = [
                record
                for record in records
                if record.manifest.kind == kind and record.manifest.settings_scope == SettingsScope.PAGE
            ]
            if not group:
                continue
            self.navigationInterface.addItemHeader(
                tr(f"plugin.kind.{kind.value}"), NavigationItemPosition.SCROLL
            )
            for record in group:
                page = PluginPage(plugins, record, self, self._services)
                self._plugin_pages[record.id] = page
                self.addSubInterface(
                    page,
                    fluent_icon(record.manifest.icon),
                    plugins.display_name(record.id),
                    NavigationItemPosition.SCROLL,
                )

    def show_plugin(self, plugin_id: str) -> None:
        page = self._plugin_pages.get(plugin_id)
        if page is not None:
            self.switchTo(page)

    def bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def prepare_quit(self) -> None:
        """Accept subsequent close events without issuing another quit request."""
        self._quitting = True

    def toggle_visibility(self) -> None:
        """Hide a visible main window, or restore a hidden/minimized one."""
        if self.is_present:
            self.hide()
            self.hiddenToTray.emit()
        else:
            self.bring_to_front()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.presenceChanged.emit(self.is_present)

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self.presenceChanged.emit(self.is_present)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.presenceChanged.emit(self.is_present)

    @property
    def is_present(self) -> bool:
        return self.isVisible() and not self.isMinimized()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._quitting:
            # The Windows frameless base may hide on Alt+F4 when quit-on-close is disabled.
            event.accept()
            return
        event.ignore()
        self.hide()
        self.hiddenToTray.emit()

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.center().y() - self.height() // 2)
