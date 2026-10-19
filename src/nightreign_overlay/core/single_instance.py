"""Single instance guard: a second launch asks the running instance to show itself, then exits."""

from __future__ import annotations

import getpass
import hashlib

from PyQt6.QtCore import QDir, QLockFile, QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from nightreign_overlay.core.log import get_logger

log = get_logger(__name__)

_ACTIVATE_MESSAGE = b"activate"
_TIMEOUT_MS = 300


class SingleInstance(QObject):
    activationRequested = pyqtSignal()

    def __init__(self, key: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._key = f"{key}-{getpass.getuser()}"
        self._server: QLocalServer | None = None
        digest = hashlib.sha256(self._key.encode()).hexdigest()
        self._lock = QLockFile(f"{QDir.tempPath()}/{digest}.lock")

    def acquire(self) -> bool:
        """Return True if this is the primary instance; otherwise notify the primary and return False."""
        if self._notify_primary():
            return False
        # Serialize stale-address removal and listening across simultaneous launches.
        if not self._lock.tryLock(0):
            self._notify_primary()
            return False
        QLocalServer.removeServer(self._key)
        self._server = QLocalServer(self)
        if not self._server.listen(self._key):
            log.error("Single instance server failed to listen: %s", self._server.errorString())
            self.release()
            return False
        self._server.newConnection.connect(self._on_new_connection)
        return True

    def _notify_primary(self) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self._key)
        if not socket.waitForConnected(_TIMEOUT_MS):
            return False
        socket.write(_ACTIVATE_MESSAGE)
        socket.waitForBytesWritten(_TIMEOUT_MS)
        socket.disconnectFromServer()
        return True

    def release(self) -> None:
        """Stop listening so that a freshly spawned instance (e.g. on restart) can become primary."""
        if self._server is not None:
            self._server.close()
            self._server = None
        self._lock.unlock()

    def _on_new_connection(self) -> None:
        assert self._server is not None
        while (connection := self._server.nextPendingConnection()) is not None:
            connection.waitForReadyRead(_TIMEOUT_MS)
            if connection.readAll().data() == _ACTIVATE_MESSAGE:
                self.activationRequested.emit()
            connection.disconnectFromServer()
            connection.deleteLater()
