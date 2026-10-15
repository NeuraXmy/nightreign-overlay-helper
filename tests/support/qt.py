"""Qt event processing helpers shared by core, UI, and plugin tests."""

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer


def process_events(timeout_ms: int = 50) -> None:
    """Run the event loop briefly so queued signals and timers are delivered."""
    loop = QEventLoop()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    QCoreApplication.processEvents()
