"""Tracks whether the game window is in the foreground."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from nightreign_overlay.core.events import EventBus
from nightreign_overlay.meta import GAME_WINDOW_TITLE
from nightreign_overlay.platforms import PlatformBackend


@dataclass(frozen=True)
class GameForegroundChanged:
    """Published on the event bus whenever the game gains or loses the foreground."""

    foreground: bool


class GameWindowMonitor(QObject):
    """Polls the foreground window title.

    On platforms without foreground detection the game is assumed to always be in the foreground, so overlays
    configured as "only show while the game is focused" remain visible for debugging.
    """

    foregroundChanged = pyqtSignal(bool)

    POLL_INTERVAL_MS = 500

    def __init__(
        self,
        backend: PlatformBackend,
        events: EventBus,
        window_title: str = GAME_WINDOW_TITLE,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend = backend
        self._events = events
        self._title = window_title.lower()
        self._foreground = not backend.supports_foreground_detection
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

    @property
    def supported(self) -> bool:
        return self._backend.supports_foreground_detection

    @property
    def is_foreground(self) -> bool:
        return self._foreground

    def start(self) -> None:
        if self.supported:
            self._poll()
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _poll(self) -> None:
        title = self._backend.foreground_window_title()
        foreground = title is not None and self._title in title.lower()
        if foreground != self._foreground:
            self._foreground = foreground
            self.foregroundChanged.emit(foreground)
            self._events.publish(GameForegroundChanged(foreground))
