"""Application bootstrap: wires core services, plugins and the main window together."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from PyQt6.QtCore import QLocale, QObject, QProcess, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
from qfluentwidgets import FluentTranslator, InfoBar

from nightreign_overlay.core import i18n
from nightreign_overlay.core.app_config import APP_CONFIG_NAMESPACE, AppConfig
from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.debug import DebugImageApi, DebugImageService
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.game_window import ForegroundPolicy, GameWindowMonitor
from nightreign_overlay.core.log import get_logger, set_log_level, setup_logging
from nightreign_overlay.core.paths import DATA_DIR_ENV, log_dir, resource_path, settings_file
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.core.single_instance import SingleInstance
from nightreign_overlay.meta import APP_AUTHOR, APP_ID, APP_NAME, APP_VERSION
from nightreign_overlay.platforms import PlatformBackend, create_backend
from nightreign_overlay.platforms.shell import configure_taskbar_identity
from nightreign_overlay.plugin import PluginManager
from nightreign_overlay.ui.components.updates import UpdateController
from nightreign_overlay.ui.main_window import MainWindow
from nightreign_overlay.ui.overlay import OverlayManager
from nightreign_overlay.ui.theme import app_icon, apply_theme
from nightreign_overlay.ui.tray import TrayIcon

log = get_logger(__name__)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_ID, description=APP_NAME)
    parser.add_argument("--minimized", action="store_true", help="start hidden in the system tray")
    parser.add_argument("--data-dir", help=f"directory for settings and logs (also via ${DATA_DIR_ENV})")
    parser.add_argument("--debug", action="store_true", help="force DEBUG logging")
    # Qt consumes its own options (e.g. -platform); ignore anything we do not know.
    args, _unknown = parser.parse_known_args(argv)
    return args


def resolve_language(setting: str) -> str:
    return i18n.match_language(QLocale.system().name()) if setting == "auto" else setting


class Application(QObject):
    """Owns every long-lived object of a running instance."""

    def __init__(self, qt_app: QApplication, instance: SingleInstance, args: argparse.Namespace) -> None:
        super().__init__()
        self._qt_app = qt_app
        self._instance = instance
        self._args = args
        self._shut_down = False
        self._window_hidden_for_selection = False

        self.store = ConfigStore(settings_file(), self)
        self.config = self.store.bind(AppConfig, APP_CONFIG_NAMESPACE)
        if not args.debug:
            set_log_level(self.config.log_level.value)

        self._init_translations()
        apply_theme(self.config)

        self.backend = create_backend()
        self.events = EventBus(self)
        self.services = ServiceRegistry(self)
        self.game_monitor = GameWindowMonitor(self.backend, self.events, parent=self)
        self.overlays = OverlayManager(self.backend, self.config, self.game_monitor, self)
        self.services.register(PlatformBackend, self.backend)
        self.services.register(AppConfig, self.config)
        self.services.register(GameWindowMonitor, self.game_monitor)
        self.services.register(ForegroundPolicy, self.overlays.foreground)
        self.services.register(OverlayManager, self.overlays)
        self.debug_images = DebugImageService(self.config.debug_images_enabled)
        self.services.register(DebugImageApi, self.debug_images)

        self.plugins = PluginManager(self.store, self.translator, self.services, self.events, self)
        self.plugins.discover()
        self.plugins.load_all()

        self.window = MainWindow(self.config, self.plugins, self.overlays, self.game_monitor)
        self.updates = UpdateController(self.window, self)
        self.updates.busyChanged.connect(self.window.aboutPage.set_update_busy)
        self.window.aboutPage.checkUpdatesRequested.connect(self.updates.check)
        self.window.aboutPage.changelogRequested.connect(lambda: self.updates.check(history=True))
        self.tray = TrayIcon(self.window) if QSystemTrayIcon.isSystemTrayAvailable() else None
        self._connect_signals()

    def _init_translations(self) -> None:
        language = resolve_language(self.config.language.value)
        self.translator = i18n.Translator(language)
        self.translator.load_dir(i18n.CORE_NAMESPACE, resource_path("i18n"))
        i18n.install(self.translator)
        # Built-in strings of qfluentwidgets ("On", "Off", dialogs...).
        self._fluent_translator = FluentTranslator(QLocale(language))
        self._qt_app.installTranslator(self._fluent_translator)
        log.info("Language: %s", language)

    def _connect_signals(self) -> None:
        self.store.saveFailed.connect(self._on_settings_save_failed)
        self._instance.activationRequested.connect(self.window.bring_to_front)
        self.overlays.mainWindowRequested.connect(self.window.bring_to_front)
        self.overlays.mainWindowHideRequested.connect(self._hide_window_for_selection)
        self.overlays.mainWindowShowRequested.connect(self._restore_window_after_selection)
        self.overlays.quitRequested.connect(self.quit)
        self.window.quitRequested.connect(self.quit)
        self.window.hiddenToTray.connect(self._on_hidden_to_tray)
        self.window.settingsPage.restartRequested.connect(self.restart)
        foreground = self.overlays.foreground
        self.window.presenceChanged.connect(lambda present: foreground.set_ui_active("main_window", present))
        if self.tray is not None:
            self.tray.showRequested.connect(self.window.bring_to_front)
            self.tray.toggleRequested.connect(self.window.toggle_visibility)
            self.tray.quitRequested.connect(self.quit)
            self.tray.menu.aboutToShow.connect(lambda: foreground.set_ui_active("tray_menu", True))
            self.tray.menu.aboutToHide.connect(lambda: foreground.set_ui_active("tray_menu", False))
        self._qt_app.aboutToQuit.connect(self._shutdown)

    def _on_settings_save_failed(self, error: str) -> None:
        self.window.bring_to_front()
        InfoBar.error(
            title=i18n.tr("settings_save.failed_title"),
            content=i18n.tr("settings_save.failed_content", error=error),
            duration=-1,
            parent=self.window,
        )

    def start(self) -> None:
        log.info(
            "%s %s starting (platform=%s, transparent overlays=%s)",
            APP_NAME,
            APP_VERSION,
            self.backend.name,
            self.overlays.transparent_mode,
        )
        self.game_monitor.start()
        self.plugins.start()
        if self.tray is not None:
            self.tray.show()
        minimized = self._args.minimized or self.config.start_minimized.value
        if not minimized or self.tray is None:
            self.window.show()
        self.updates.start(self.config.auto_check_updates.value)

    def quit(self) -> None:
        self.window.prepare_quit()
        self._shutdown()
        self._qt_app.quit()

    def restart(self) -> None:
        log.info("Restarting")
        self._shutdown()
        # Free the single instance key first, otherwise the new process would just activate this one.
        self._instance.release()
        if getattr(sys, "frozen", False):
            program, arguments = sys.executable, sys.argv[1:]
        else:
            program, arguments = sys.executable, sys.orig_argv[1:]
        if not QProcess.startDetached(program, arguments, os.getcwd())[0]:
            log.error("Failed to restart: could not start %s", program)
        self.window.prepare_quit()
        self._qt_app.quit()

    def _shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self.updates.shutdown()
        self.plugins.shutdown()
        self.debug_images.close()
        self.game_monitor.stop()
        if self.tray is not None:
            self.tray.hide()
        self.store.flush()
        log.info("Shut down")

    def _hide_window_for_selection(self) -> None:
        # Only the main window leaves the screen; overlays stay so their position can be referenced.
        self._window_hidden_for_selection = self.window.isVisible() and not self.window.isMinimized()
        if self._window_hidden_for_selection:
            self.window.hide()

    def _restore_window_after_selection(self) -> None:
        # A selection started from the game via hotkey must not pull the main window over it.
        if self._window_hidden_for_selection:
            self._window_hidden_for_selection = False
            self.window.bring_to_front()

    def _on_hidden_to_tray(self) -> None:
        if self.tray is None or self.config.tray_hint_shown.value:
            return
        self.tray.notify(APP_NAME, i18n.tr("tray.hidden_hint"))
        self.config.tray_hint_shown.set(True)


def run(argv: Sequence[str]) -> int:
    args = parse_args(argv[1:])
    if args.data_dir:
        os.environ[DATA_DIR_ENV] = os.path.abspath(args.data_dir)
    setup_logging(log_dir(), "DEBUG" if args.debug else "INFO")

    configure_taskbar_identity()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qt_app = QApplication(list(argv))
    qt_app.setApplicationName(APP_NAME)
    qt_app.setApplicationVersion(APP_VERSION)
    qt_app.setOrganizationName(APP_AUTHOR)
    qt_app.setWindowIcon(app_icon())
    qt_app.setQuitOnLastWindowClosed(False)

    instance = SingleInstance(APP_ID)
    if not instance.acquire():
        log.info("Another instance is already running; asked it to show itself")
        return 0

    app = Application(qt_app, instance, args)
    app.start()
    return qt_app.exec()
