"""Closing exits; hiding is a separate tray action."""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QSystemTrayIcon, QWidget

from nightreign_overlay.app import Application
from nightreign_overlay.ui.main_window import MainWindow
from nightreign_overlay.ui.tray import TrayIcon


class Window(QWidget):
    quitRequested = pyqtSignal()
    hiddenToTray = pyqtSignal()
    closeEvent = MainWindow.closeEvent
    toggle_visibility = MainWindow.toggle_visibility
    prepare_quit = MainWindow.prepare_quit
    is_present = MainWindow.is_present

    def __init__(self):
        super().__init__()
        self._quitting = False

    def bring_to_front(self):
        self.showNormal()
        self.show()


def test_tray_toggle_and_exit_are_independent(qapp):
    window = Window()
    tray = TrayIcon(window)
    tray.toggleRequested.connect(window.toggle_visibility)
    exits = []
    tray.quitRequested.connect(lambda: exits.append(True))
    actions = tray.menu.menuActions()
    window.show()
    actions[0].trigger()
    assert not window.isVisible() and exits == []
    actions[0].trigger()
    assert window.isVisible() and exits == []
    actions[1].trigger()
    assert exits == [True]  # One click even when the main window is open.
    window.hide()
    actions[1].trigger()
    assert exits == [True, True]
    shown = []
    tray.showRequested.connect(lambda: shown.append(True))
    tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert shown == [True]
    tray.deleteLater()
    window.deleteLater()


@pytest.mark.parametrize("visible", [True, False])
def test_close_requests_exit_regardless_of_visibility(qapp, visible):
    window = Window()
    if visible:
        window.show()
    exits, hidden = [], []
    window.quitRequested.connect(lambda: exits.append(True))
    window.hiddenToTray.connect(lambda: hidden.append(True))
    event = QCloseEvent()
    window.closeEvent(event)
    assert exits == [True] and hidden == []
    assert not event.isAccepted()
    window.prepare_quit()
    window.closeEvent(event)
    assert event.isAccepted() and exits == [True]
    window.hide()
    window.deleteLater()


def test_quit_prepares_window_before_shutdown(qapp):
    app = Application.__new__(Application)
    QObject.__init__(app)
    window = Window()
    window.show()
    app.window = window
    calls = []

    def shutdown():
        event = QCloseEvent()
        window.closeEvent(event)
        assert event.isAccepted()
        calls.append("shutdown")

    app._shutdown = shutdown
    app._qt_app = SimpleNamespace(quit=lambda: calls.append("quit"))
    app.quit()
    assert calls == ["shutdown", "quit"]
    window.hide()
    window.deleteLater()
    app.deleteLater()
