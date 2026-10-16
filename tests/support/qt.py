"""Qt event processing helpers shared by core, UI, and plugin tests."""

from PyQt6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject, QTimer


def delete_qobjects(*objects: QObject) -> None:
    """Finish deferred deletion while Python references still keep the object trees intact.

    Tests do not run QApplication.exec(). Returning immediately after deleteLater() can let Python
    collect child wrappers before Qt processes pending polish events in the next test's event loop.
    Only deliver deletion events for the requested roots; do not run unrelated queued callbacks.
    """
    for obj in objects:
        obj.deleteLater()
        QCoreApplication.sendPostedEvents(obj, QEvent.Type.DeferredDelete)


def process_events(timeout_ms: int = 50) -> None:
    """Run the event loop briefly so queued signals and timers are delivered."""
    loop = QEventLoop()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    QCoreApplication.processEvents()
