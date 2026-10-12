"""System tray icon and menu."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QSystemTrayIcon, QWidget
from qfluentwidgets import Action, FluentIcon, SystemTrayMenu

from nightreign_overlay.core.i18n import tr
from nightreign_overlay.meta import APP_NAME
from nightreign_overlay.ui.theme import app_icon


class TrayIcon(QSystemTrayIcon):
    showRequested = pyqtSignal()
    quitRequested = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(app_icon(), parent)
        self.setToolTip(APP_NAME)

        self.menu = SystemTrayMenu(parent=parent)
        self.menu.addActions(
            [
                Action(
                    FluentIcon.HOME, tr("tray.show"), self.menu, triggered=lambda: self.showRequested.emit()
                ),
                Action(
                    FluentIcon.CLOSE, tr("tray.quit"), self.menu, triggered=lambda: self.quitRequested.emit()
                ),
            ]
        )
        self.setContextMenu(self.menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.showRequested.emit()

    def notify(self, title: str, message: str) -> None:
        self.showMessage(title, message, app_icon(), 3000)
