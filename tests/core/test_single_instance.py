"""Single-instance ownership covers failed listening and simultaneous launches."""

import uuid
from types import SimpleNamespace

from nightreign_overlay.core import single_instance as module


def test_listen_failure_never_grants_primary(qapp, monkeypatch):
    guard = module.SingleInstance(f"test-{uuid.uuid4()}")
    monkeypatch.setattr(guard, "_notify_primary", lambda: False)

    class FailedServer:
        def __init__(self, *args):
            pass

        @staticmethod
        def removeServer(*args):
            pass

        def listen(self, key):
            return False

        def errorString(self):
            return "access denied"

        def close(self):
            pass

    monkeypatch.setattr(module, "QLocalServer", FailedServer)
    assert guard.acquire() is False
    assert guard._server is None
    assert not guard._lock.isLocked()


def test_launch_race_does_not_unlink_primary(qapp, monkeypatch):
    removed = []

    class Server:
        def __init__(self, *args):
            self.newConnection = SimpleNamespace(connect=lambda *_: None)
            self.listening = False

        @staticmethod
        def removeServer(key):
            removed.append(key)

        def listen(self, key):
            self.listening = True
            return True

        def isListening(self):
            return self.listening

        def close(self):
            self.listening = False

    monkeypatch.setattr(module, "QLocalServer", Server)
    key = f"test-{uuid.uuid4()}"
    primary = module.SingleInstance(key)
    secondary = module.SingleInstance(key)
    monkeypatch.setattr(primary, "_notify_primary", lambda: False)
    try:
        assert primary.acquire()
        # Simulate the secondary checking before the primary started listening.
        monkeypatch.setattr(secondary, "_notify_primary", lambda: False)
        assert not secondary.acquire()
        assert primary._server.isListening()
        assert len(removed) == 1
    finally:
        secondary.release()
        primary.release()
