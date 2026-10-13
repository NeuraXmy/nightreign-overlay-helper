"""Tracks whether the game window is in the foreground."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.log import get_logger
from nightreign_overlay.meta import GAME_WINDOW_TITLE
from nightreign_overlay.platforms import PlatformBackend

log = get_logger(__name__)


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


class ForegroundPolicy(QObject):
    """The single "only show and detect while the game is in the foreground" rule (legacy semantics).

    While the option is on and the game is in the background:

    * overlays are hidden and hotkeys are ignored, unless the user is interacting with this app (main
      window shown, tray / overlay context menu open, region selection running) — otherwise the overlays
      could not be inspected while adjusting settings and a menu would vanish together with its overlay;
    * detection (frame capture) is paused, with no exception.

    This gate is only one factor of an overlay's visibility; see :meth:`OverlayWindow.should_be_visible`.
    """

    changed = pyqtSignal()

    def __init__(self, config: AppConfig, monitor: GameWindowMonitor, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._monitor = monitor
        self._ui_sources: set[str] = set()
        config.only_when_game_foreground.valueChanged.connect(self._on_option_changed)
        monitor.foregroundChanged.connect(lambda _foreground: self.changed.emit())

    @property
    def enabled(self) -> bool:
        return self._config.only_when_game_foreground.value

    @property
    def ui_active(self) -> bool:
        return bool(self._ui_sources)

    @property
    def display_allowed(self) -> bool:
        return not self.enabled or self._monitor.is_foreground or self.ui_active

    @property
    def input_allowed(self) -> bool:
        return self.display_allowed

    @property
    def detection_allowed(self) -> bool:
        return not self.enabled or self._monitor.is_foreground

    def set_ui_active(self, source: str, active: bool) -> None:
        """Mark an app UI surface (e.g. ``"main_window"``) as currently used or no longer used."""
        if active == (source in self._ui_sources):
            return
        if active:
            self._ui_sources.add(source)
        else:
            self._ui_sources.discard(source)
        self.changed.emit()

    def is_ui_active(self, source: str) -> bool:
        """Whether a particular editing surface is open (e.g. for legacy overlay dragging)."""
        return source in self._ui_sources

    def _on_option_changed(self, enabled: bool) -> None:
        log.info("Overlay only show when game foreground: %s", enabled)
        self.changed.emit()
