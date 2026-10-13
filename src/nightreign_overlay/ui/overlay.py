"""Overlay window base class and the manager that coordinates all overlays.

An overlay runs in one of two presentations, selected by ``AppConfig.overlay_mode``:

* **transparent** — frameless, translucent, always on top and optionally click-through. This is the normal
  mode on Windows.
* **window** — an ordinary (still always-on-top) window with a title bar and an opaque background. Used as a
  fallback where translucent top-level windows misbehave, and handy for debugging on macOS.

Plugins obtain the :class:`OverlayManager` from the service registry and subclass :class:`OverlayWindow`,
implementing :meth:`OverlayWindow.paint_overlay` in unscaled coordinates.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QContextMenuEvent,
    QGuiApplication,
    QMouseEvent,
    QMoveEvent,
    QPainter,
    QPaintEvent,
)
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import Action, FluentIcon, RoundMenu

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.config import ChoiceOption, ConfigGroup, Option, RangeOption
from nightreign_overlay.core.game_window import ForegroundPolicy, GameWindowMonitor
from nightreign_overlay.core.i18n import tr
from nightreign_overlay.core.log import get_logger
from nightreign_overlay.platforms import PlatformBackend

log = get_logger(__name__)

#: Background painted behind overlay content in window mode.
WINDOW_MODE_BACKGROUND = QColor(32, 32, 32)
#: Distance between the top of the primary screen and a freshly placed overlay.
DEFAULT_TOP_MARGIN = 48


def _is_position(value: Any) -> bool:
    return value is None or (
        isinstance(value, list)
        and len(value) == 2
        and all(v is None or (isinstance(v, int) and not isinstance(v, bool)) for v in value)
    )


class OverlayConfig(ConfigGroup):
    """Options shared by every overlay window. Bind one instance per overlay (usually as a config section)."""

    #: Top-left corner in global coordinates; None components follow the default position on that axis.
    position = Option[list[int | None] | None](None, validator=_is_position)
    opacity = RangeOption(100, 20, 100)
    scale = RangeOption(100, 50, 200)
    input_mode = ChoiceOption("normal", ("normal", "locked", "passthrough"))


class OverlayManager(QObject):
    """Keeps overlays consistent with global settings: presentation mode, game focus and z-order."""

    #: An overlay asked for the main window (e.g. from its context menu).
    mainWindowRequested = pyqtSignal()
    #: Temporarily hide the main window while a full-screen selector has focus.
    mainWindowHideRequested = pyqtSignal()
    #: Restore the main window after a selector that hid it has closed.
    mainWindowShowRequested = pyqtSignal()
    #: An overlay requested orderly application shutdown from its context menu.
    quitRequested = pyqtSignal()

    TOPMOST_INTERVAL_MS = 1000

    def __init__(
        self,
        backend: PlatformBackend,
        app_config: AppConfig,
        game_monitor: GameWindowMonitor,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend = backend
        self._app_config = app_config
        self._game_monitor = game_monitor
        self._windows: list[OverlayWindow] = []
        #: Shared with capture / input through the service registry.
        self.foreground = ForegroundPolicy(app_config, game_monitor, self)

        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(self.TOPMOST_INTERVAL_MS)
        self._topmost_timer.timeout.connect(self._reassert_topmost)
        self._topmost_timer.start()

        app_config.overlay_mode.valueChanged.connect(self._on_mode_changed)
        self.foreground.changed.connect(self._on_foreground_changed)
        # A region selection takes the focus from the game; overlays must stay as a reference.
        self.mainWindowHideRequested.connect(lambda: self.foreground.set_ui_active("region_selection", True))
        self.mainWindowShowRequested.connect(lambda: self.foreground.set_ui_active("region_selection", False))

    @property
    def backend(self) -> PlatformBackend:
        return self._backend

    @property
    def transparent_mode(self) -> bool:
        mode = self._app_config.overlay_mode.value
        # Automatic mode follows the legacy default: prefer a transparent overlay everywhere.
        # Users can explicitly select ``window`` if their compositor cannot display it correctly.
        return mode != "window"

    @property
    def game_foreground(self) -> bool:
        return self._game_monitor.is_foreground

    def windows(self) -> list[OverlayWindow]:
        return list(self._windows)

    def register(self, window: OverlayWindow) -> None:
        if window not in self._windows:
            self._windows.append(window)

    def unregister(self, window: OverlayWindow) -> None:
        if window in self._windows:
            self._windows.remove(window)

    def _on_mode_changed(self, _mode: str) -> None:
        for window in self.windows():
            window.apply_window_mode()

    def _on_foreground_changed(self) -> None:
        for window in self.windows():
            window.update_visibility()
            window.update()

    def _reassert_topmost(self) -> None:
        # Borderless full screen games tend to push other topmost windows down; re-assert periodically.
        for window in self._windows:
            if window.isVisible():
                self._backend.ensure_topmost(int(window.winId()))


class OverlayWindow(QWidget):
    """Base class for overlay windows.

    Subclasses describe their content at 100% scale: pass the unscaled size to the constructor (or
    :meth:`set_base_size`) and draw in :meth:`paint_overlay`. Scaling, opacity, dragging, position
    persistence, presentation mode and focus based visibility are handled here.

    Call :meth:`show_overlay` / :meth:`hide_overlay` instead of ``show`` / ``hide`` so that visibility rules
    keep applying, and :meth:`dispose` when the overlay is no longer needed.
    """

    #: Subclasses that users position directly opt into the temporary drag affordance.
    drag_hint_enabled = False

    def __init__(
        self,
        manager: OverlayManager,
        config: OverlayConfig,
        title: str,
        base_size: QSize,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.config = config
        self._base_size = QSize(base_size)
        self._requested = False
        self._disposing = False
        self._applying_mode = False
        self._programmatic_pos: QPoint | None = None
        self._drag_offset: QPoint | None = None

        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.apply_window_mode()
        self._apply_size()
        self._apply_opacity(config.opacity.value)
        self._restore_position()

        config.opacity.valueChanged.connect(self._apply_opacity)
        config.scale.valueChanged.connect(self._on_scale_changed)
        config.input_mode.valueChanged.connect(self._on_input_mode_changed)
        config.position.valueChanged.connect(self._on_position_changed)
        manager.register(self)

    # -- public API ---------------------------------------------------------------------------

    @property
    def scale_factor(self) -> float:
        return self.config.scale.value / 100

    @property
    def base_size(self) -> QSize:
        return QSize(self._base_size)

    def set_base_size(self, size: QSize) -> None:
        self._base_size = QSize(size)
        self._apply_size()
        if self.config.position.value is None:
            # Dynamic overlays start small and grow as plugins contribute content.
            self._move_to(self._default_position())

    def show_overlay(self) -> None:
        self._requested = True
        self.update_visibility()

    def hide_overlay(self) -> None:
        self._requested = False
        self.update_visibility()

    def should_be_visible(self) -> bool:
        """Visibility = own request AND subclass conditions AND the global foreground gate.

        Own hide reasons (``hide_overlay()``, a disabled overlay, the map not being open, no HP bar...)
        always win; subclasses add theirs with ``cond and super().should_be_visible()``. The foreground
        gate can only hide, never show, an overlay.
        """
        if not self._requested:
            return False
        # In window mode the overlay can take focus itself, so focus based hiding would make it unreachable.
        if self.manager.transparent_mode:
            return self.manager.foreground.display_allowed
        return True

    def update_visibility(self) -> None:
        visible = self.should_be_visible()
        if visible and not self.isVisible():
            self.show()
        elif not visible and self.isVisible():
            self.hide()

    def apply_window_mode(self) -> None:
        """(Re)apply window flags for the current presentation mode and click-through setting."""
        transparent = self.manager.transparent_mode
        if transparent:
            flags = (
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowDoesNotAcceptFocus
                | Qt.WindowType.NoDropShadowWindowHint
            )
            if self.config.input_mode.value == "passthrough":
                flags |= Qt.WindowType.WindowTransparentForInput
        else:
            flags = (
                Qt.WindowType.Window
                | Qt.WindowType.CustomizeWindowHint
                | Qt.WindowType.WindowTitleHint
                | Qt.WindowType.WindowStaysOnTopHint
            )

        position = self.pos()
        self._applying_mode = True
        try:
            # Changing flags hides the window and may recreate the native handle.
            self.setWindowFlags(flags)
            self._move_to(position)
        finally:
            self._applying_mode = False
        self.update_visibility()
        self.update()

    def reset_position(self) -> None:
        self.config.position.set(None)

    def reset_horizontal_position(self) -> None:
        position = self.config.position.value
        self.config.position.set([None, position[1] if position is not None else None])

    def dispose(self) -> None:
        """Close and schedule deletion; the instance must not be used afterwards."""
        self._disposing = True
        self.manager.unregister(self)
        self.close()
        self.deleteLater()

    # -- subclass hooks -----------------------------------------------------------------------

    def paint_overlay(self, painter: QPainter) -> None:
        """Draw the content in unscaled coordinates within ``QRect(QPoint(), self.base_size)``."""

    def on_scale_changed(self, scale: float) -> None:
        """Called after the scale factor changed and the window was resized."""

    # -- Qt events ----------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        if not self.manager.transparent_mode:
            painter.fillRect(self.rect(), WINDOW_MODE_BACKGROUND)
        elif (
            self.drag_hint_enabled
            and self.config.input_mode.value == "normal"
            and self.manager.foreground.is_ui_active("main_window")
        ):
            # Keep the normal transparent overlay invisible until the main window is open for positioning.
            painter.fillRect(self.rect(), QColor(255, 255, 255, 20))
            painter.setPen(QColor(255, 255, 255, 50))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.scale(self.scale_factor, self.scale_factor)
        self.paint_overlay(painter)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.config.input_mode.value != "locked":
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self._save_position()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        # Window mode: the user may drag the native title bar, which bypasses our mouse handlers. Moves made
        # by us are recognised by their target so that e.g. a reset keeps following the default position.
        user_move = self.pos() != self._programmatic_pos
        if user_move and self.config.input_mode.value == "locked" and not self._applying_mode:
            # Window mode can still be moved through its native title bar; restore the
            # configured position so the lock applies outside transparent mode as well.
            self._on_position_changed(self.config.position.value)
        elif user_move and self._drag_offset is None and not self._applying_mode and self.isVisible():
            self._save_position()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Keep the overlay menu equivalent to the legacy open-settings / quit menu."""
        menu = RoundMenu(parent=self)
        menu.addAction(
            Action(
                FluentIcon.HOME,
                tr("overlay.menu.open_main_window"),
                menu,
                triggered=self.manager.mainWindowRequested.emit,
            )
        )
        menu.addAction(
            Action(
                FluentIcon.CLOSE,
                tr("overlay.menu.quit"),
                menu,
                triggered=self.manager.quitRequested.emit,
            )
        )
        # Legacy is_menu_opened: the menu takes the focus from the game, which must not hide its overlay.
        self.manager.foreground.set_ui_active("overlay_menu", True)
        try:
            menu.exec(event.globalPos())
        finally:
            self.manager.foreground.set_ui_active("overlay_menu", False)

    def closeEvent(self, event: QCloseEvent) -> None:
        # Overlays are owned by plugins; closing them from the window manager (Alt+F4, Cmd+W) is ignored.
        if self._disposing or not event.spontaneous():
            super().closeEvent(event)
        else:
            event.ignore()

    # -- internals ----------------------------------------------------------------------------

    def _apply_size(self) -> None:
        scale = self.scale_factor
        self.setFixedSize(round(self._base_size.width() * scale), round(self._base_size.height() * scale))
        self.updateGeometry()
        self.update()

    def _apply_opacity(self, opacity: int) -> None:
        self.setWindowOpacity(opacity / 100)

    def _on_scale_changed(self, _scale: int) -> None:
        self._apply_size()
        if self.config.position.value is None or self.config.position.value[0] is None:
            # The default position depends on the width, so keep the overlay centred.
            self._move_to(self._default_position())
        self.on_scale_changed(self.scale_factor)

    def _on_input_mode_changed(self, _mode: str) -> None:
        if self.manager.transparent_mode:
            self.apply_window_mode()

    def _on_position_changed(self, value: list[int | None] | None) -> None:
        default = self._default_position()
        position = (
            default
            if value is None
            else QPoint(
                value[0] if value[0] is not None else default.x(),
                value[1] if value[1] is not None else default.y(),
            )
        )
        if position != self.pos():
            self._move_to(position)

    def _move_to(self, position: QPoint) -> None:
        """Move without persisting; the position setting only records moves made by the user."""
        self._programmatic_pos = QPoint(position)
        self.move(position)

    def _save_position(self) -> None:
        self.config.position.set([self.x(), self.y()])

    def _restore_position(self) -> None:
        value = self.config.position.value
        default = self._default_position()
        position = (
            default
            if value is None
            else QPoint(
                value[0] if value[0] is not None else default.x(),
                value[1] if value[1] is not None else default.y(),
            )
        )
        self._move_to(position if self._is_on_screen(position) else default)

    def _is_on_screen(self, position: QPoint) -> bool:
        rect = QRect(position, self.size())
        return any(screen.availableGeometry().intersects(rect) for screen in QGuiApplication.screens())

    def _default_position(self) -> QPoint:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QPoint(0, 0)
        area = screen.availableGeometry()
        return QPoint(area.center().x() - self.width() // 2, area.top() + DEFAULT_TOP_MARGIN)
