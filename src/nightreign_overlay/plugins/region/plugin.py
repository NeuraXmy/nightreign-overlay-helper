"""Region calibration plugin; the selector mirrors the legacy ``CaptureRegionWindow`` interaction."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from PyQt6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QWidget

from nightreign_overlay.platforms import PlatformBackend
from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest, SettingsScope
from nightreign_overlay.plugins.region.api import RegionApi, RegionTarget
from nightreign_overlay.plugins.region.config import RegionConfig
from nightreign_overlay.ui.overlay import OverlayManager

#: Time for the window server to remove the hidden main window before the screen is frozen.
_HIDE_SETTLE_MS = 250
#: Size of the legacy corner/center resize handles.
_HANDLE_SIZE = 8
#: Legacy colour of the "DAY I" annotation button and rectangle; the default for other targets.
_RECT_COLOR = "#686435"
_ANNOTATE_STYLE = (
    "background-color: {color}; color: white; border-radius: 4px; padding: 8px; font-size: 16px;"
)


class _RegionService(RegionApi):
    def __init__(self, plugin: RegionPlugin) -> None:
        self._plugin = plugin

    def request_region(self, key: str, label: str | None = None, color: str | None = None) -> QRect | None:
        ctx = self._plugin.ctx
        target = RegionTarget(key, label or ctx.tr("selection.annotate"), color)
        result = self._select([target], require_freeze=False)
        selected = result[0].get(0) if result is not None else None
        if selected is None:
            ctx.log.warning("Region %s setting canceled", key)
            return None
        self.save_region_for_test(key, selected)
        ctx.log.info("Region %s saved: %s", key, list(selected.getRect()))
        return selected

    def request_samples(self, targets: Sequence[RegionTarget]) -> dict[str, QImage] | None:
        result = self._select(targets, require_freeze=True)
        if result is None:
            return None
        selections, dialog = result
        samples = {}
        for index, rect in selections.items():
            sample = dialog.sample(index)
            if sample is not None:
                samples[targets[index].id] = sample
                self._plugin.ctx.log.info("Sampled %s at %s", targets[index].id, list(rect.getRect()))
        return samples

    def _select(
        self, targets: Sequence[RegionTarget], *, require_freeze: bool
    ) -> tuple[dict[int, QRect], _SelectionDialog] | None:
        """Hide the main window, run the selector and return its rectangles, or ``None`` on cancel."""
        ctx = self._plugin.ctx
        overlays = ctx.services.get(OverlayManager)
        backend = ctx.services.get(PlatformBackend)
        freeze = backend is None or backend.has_screen_capture_access()
        if not freeze and backend is not None:
            backend.request_screen_capture_access()
            if require_freeze:
                ctx.log.error("Screen capture permission missing; cannot sample the frozen screen")
                return None
            # Without permission the frozen frame would only show this app's own windows, so the
            # selector stays translucent over the live screen instead.
            ctx.log.warning("Screen capture permission missing; selecting over the live screen")
        if overlays is not None:
            overlays.mainWindowHideRequested.emit()
        try:
            _wait(_HIDE_SETTLE_MS)
            texts = _SelectionTexts(
                annotate=ctx.tr("selection.annotate"),
                hint=ctx.tr("selection.hint"),
                cancel=ctx.tr("selection.cancel"),
                save=ctx.tr("selection.save"),
            )
            annotations = [(target.label, target.color or _RECT_COLOR) for target in targets]
            window = _SelectionDialog(texts, freeze, ctx.log, annotations)
            selections = window.run()
        finally:
            if overlays is not None:
                overlays.mainWindowShowRequested.emit()
        if selections is None:
            return None
        return selections, window

    def region(self, key: str) -> QRect | None:
        value = self._plugin.config.regions.value.get(key)
        return QRect(*value) if value is not None else None

    def save_region_for_test(self, key: str, rect: QRect) -> None:
        if rect.width() <= 0 or rect.height() <= 0:
            raise ValueError("a calibrated region must have a positive size")
        region_value = [rect.x(), rect.y(), rect.width(), rect.height()]
        regions = {**self._plugin.config.regions.value, key: region_value}
        self._plugin.config.regions.set(regions)


class RegionPlugin(Plugin):
    manifest = PluginManifest(
        id="region",
        kind=PluginKind.INFRASTRUCTURE,
        icon="CROP",
        settings_scope=SettingsScope.HIDDEN,
        order=20,
    )

    def on_load(self) -> None:
        self.config = self.ctx.config(RegionConfig)

    def on_activate(self) -> None:
        self.ctx.provide(RegionApi, _RegionService(self))


def _wait(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def _scale_rect(rect: QRect, ratio: float) -> QRect:
    return QRect(
        round(rect.x() * ratio),
        round(rect.y() * ratio),
        round(rect.width() * ratio),
        round(rect.height() * ratio),
    )


class _SelectionTexts:
    def __init__(self, annotate: str, hint: str, cancel: str, save: str) -> None:
        self.annotate = annotate
        self.hint = hint
        self.cancel = cancel
        self.save = save


_HANDLE_CURSORS = {
    "top_left": Qt.CursorShape.SizeFDiagCursor,
    "bottom_right": Qt.CursorShape.SizeFDiagCursor,
    "top_right": Qt.CursorShape.SizeBDiagCursor,
    "bottom_left": Qt.CursorShape.SizeBDiagCursor,
    "center": Qt.CursorShape.SizeAllCursor,
}


class _ResizableRect:
    """A drawn rectangle with legacy corner/center handles."""

    def __init__(self, rect: QRect, color: QColor, annotation: int = 0) -> None:
        self.rect = rect.normalized()
        self.color = color
        self.annotation = annotation
        self.handles: dict[str, QRect] = {}
        self._update_handles()

    def _update_handles(self) -> None:
        s = _HANDLE_SIZE
        rect = self.rect
        self.handles = {
            "top_left": QRect(rect.left() - s // 2, rect.top() - s // 2, s, s),
            "top_right": QRect(rect.right() - s // 2, rect.top() - s // 2, s, s),
            "bottom_left": QRect(rect.left() - s // 2, rect.bottom() - s // 2, s, s),
            "bottom_right": QRect(rect.right() - s // 2, rect.bottom() - s // 2, s, s),
            "center": QRect(rect.center().x() - s // 2, rect.center().y() - s // 2, s, s),
        }

    def draw(self, painter: QPainter) -> None:
        painter.setPen(QPen(self.color, 1, Qt.PenStyle.SolidLine))
        fill = QColor(self.color)
        fill.setAlpha(80)
        painter.setBrush(QBrush(fill))
        painter.drawRect(self.rect)
        painter.setBrush(QBrush(Qt.GlobalColor.white))
        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        for handle in self.handles.values():
            painter.drawRect(handle)

    def hit_test(self, pos: QPoint) -> str | None:
        for name, handle in self.handles.items():
            if handle.contains(pos):
                return name
        return "center" if self.rect.contains(pos) else None

    def update_geometry(self, press_pos: QPoint, current_pos: QPoint, handle: str) -> None:
        delta = current_pos - press_pos
        if handle == "center":
            self.rect.translate(delta)
        elif "top" in handle:
            self.rect.setTop(self.rect.top() + delta.y())
        elif "bottom" in handle:
            self.rect.setBottom(self.rect.bottom() + delta.y())
        if "left" in handle:
            self.rect.setLeft(self.rect.left() + delta.x())
        elif "right" in handle:
            self.rect.setRight(self.rect.right() + delta.x())
        self.rect = self.rect.normalized()
        self._update_handles()


class _SelectionDialog(QDialog):
    """Full-screen selector: click an annotation button, drag a box, adjust it, then save or cancel.

    With ``freeze`` the screen is captured first and shown dimmed (legacy behaviour); otherwise the
    selector is a translucent layer over the live screen so other windows stay visible. Saved
    rectangles are in device pixels (local * dpr + screen offset), matching the legacy selector.

    ``annotations`` lists ``(label, colour)`` buttons; by default one button with ``texts.annotate``.
    Like the legacy dialog, every button is optional and the last box drawn for a button wins.
    """

    def __init__(
        self,
        texts: _SelectionTexts,
        freeze: bool,
        log: logging.Logger,
        annotations: Sequence[tuple[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self._log = log
        self._annotations = list(annotations) if annotations else [(texts.annotate, _RECT_COLOR)]
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Hotkey calibration starts while the game is active; macOS hides Tool windows of inactive apps.
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setMouseTracking(True)
        # Like the legacy selector, cover the screen the cursor is on (the game's screen for hotkey use).
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is not None:
            self.setScreen(screen)
        self._screen_geometry = screen.geometry() if screen is not None else QRect()
        self._device_pixel_ratio = screen.devicePixelRatio() if screen is not None else 1.0
        self._pixmap: QPixmap | None = screen.grabWindow(0) if freeze and screen is not None else None
        self._log.info(
            "Start to capture region at screen %s with devicePixelRatio %s",
            self._screen_geometry.getRect(),
            self._device_pixel_ratio,
        )
        self.setGeometry(self._screen_geometry)
        self.setWindowTitle(self._annotations[0][0])

        self.items: list[_ResizableRect] = []
        self._color: QColor | None = None
        self._annotation = 0
        self._drawing = False
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self._active_item: _ResizableRect | None = None
        self._active_handle: str | None = None
        self._drag_pos: QPoint | None = None
        #: Saved rectangles in global device pixels, keyed by annotation index.
        self.selections: dict[int, QRect] = {}
        self._local_selections: dict[int, QRect] = {}
        self._setup_ui(texts)

    @property
    def selected(self) -> QRect | None:
        """The saved rectangle of the first annotation."""
        return self.selections.get(0)

    @property
    def annotateButton(self) -> QPushButton:
        return self.annotateButtons[0]

    def _setup_ui(self, texts: _SelectionTexts) -> None:
        size = self._screen_geometry.size()

        def place(widget: QWidget, x: float, y: float) -> None:
            widget.move(int(size.width() * x), int(size.height() * y))

        self.annotateButtons: list[QPushButton] = []
        for index, (label, color) in enumerate(self._annotations):
            button = QPushButton(label, self)
            button.setFixedHeight(32)
            button.setStyleSheet(_ANNOTATE_STYLE.format(color=color))
            button.clicked.connect(lambda _checked=False, index=index: self._start_annotation(index))
            place(button, 0.8, 0.1 + 0.1 * index)
            self.annotateButtons.append(button)

        self.hintLabel = QLabel(texts.hint, self)
        self.hintLabel.setWordWrap(True)
        self.hintLabel.setFixedWidth(max(1, int(size.width() * 0.18)))
        self.hintLabel.setStyleSheet(
            "background-color: rgba(0, 0, 0, 160); color: white; border-radius: 4px; padding: 8px; "
            "font-size: 14px;"
        )
        place(self.hintLabel, 0.8, 0.1 + 0.1 * len(self._annotations))

        self.cancelButton = self._control_button(texts.cancel, "#b3b3b3", self._cancel)
        place(self.cancelButton, 0.8, 0.5)
        self.saveButton = self._control_button(texts.save, "#ffffff", self._save)
        place(self.saveButton, 0.8, 0.6)

    def _control_button(self, text: str, color: str, slot: Callable[[], None]) -> QPushButton:
        button = QPushButton(text, self)
        button.setFixedHeight(50)
        button.setStyleSheet(
            f"background-color: {color}; color: black; border-radius: 4px; padding: 8px; font-size: 34px;"
        )
        button.clicked.connect(slot)
        return button

    def run(self) -> dict[int, QRect] | None:
        """Show without application modality and block until the user saves or cancels."""
        loop = QEventLoop()
        self.finished.connect(loop.quit)
        self.show()
        self.raise_()
        self.activateWindow()
        loop.exec()
        return dict(self.selections) if self.result() == QDialog.DialogCode.Accepted else None

    def sample(self, index: int) -> QImage | None:
        """Frozen-screen pixels inside the saved box of annotation ``index``."""
        local = self._local_selections.get(index)
        if self._pixmap is None or local is None:
            return None
        return self._pixmap.copy(_scale_rect(local, self._pixmap.devicePixelRatio())).toImage()

    def _start_annotation(self, index: int = 0) -> None:
        self._annotation = index
        self._color = QColor(self._annotations[index][1])
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _save(self) -> None:
        if not self.items:
            self._log.warning("No region drawn; nothing to save")
            return
        # Like the legacy dialog, the last rectangle drawn for the colour wins.
        self._local_selections = {item.annotation: QRect(item.rect) for item in self.items}
        self.selections = {}
        for index, local in sorted(self._local_selections.items()):
            self.selections[index] = self._to_pixels(local).translated(self._screen_geometry.topLeft())
            self._log.info(
                "Saved rect %s -> %s for %s",
                local.getRect(),
                self.selections[index].getRect(),
                self._annotations[index][1],
            )
        self.accept()

    def _cancel(self) -> None:
        self.selections = {}
        self._local_selections = {}
        self.reject()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        if self._pixmap is not None:
            painter.drawPixmap(self.rect(), self._pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        for item in self.items:
            self._reveal(painter, item.rect)
            item.draw(painter)
        if self._drawing and self._start is not None and self._current is not None:
            rect = QRect(self._start, self._current).normalized()
            self._reveal(painter, rect)
            painter.setPen(QPen(self._color or QColor(_RECT_COLOR), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

    def _reveal(self, painter: QPainter, rect: QRect) -> None:
        """Undo the dim mask inside ``rect``."""
        if self._pixmap is not None:
            painter.drawPixmap(rect, self._pixmap, _scale_rect(rect, self._pixmap.devicePixelRatio()))
            return
        # Keep a faint fill so the live area stays clickable while being highlighted.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(rect, QColor(0, 0, 0, 20))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

    def _to_pixels(self, rect: QRect) -> QRect:
        return _scale_rect(rect, self._device_pixel_ratio)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        pos = event.position().toPoint()
        self._drag_pos = pos
        for item in reversed(self.items):
            handle = item.hit_test(pos)
            if handle is not None:
                self._active_item = item
                self._active_handle = handle
                self.setCursor(_HANDLE_CURSORS[handle])
                return
        if self._color is not None:
            self._drawing = True
            self._start = pos
            self._current = pos

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._active_item is not None and self._active_handle is not None and self._drag_pos is not None:
            self._active_item.update_geometry(self._drag_pos, pos, self._active_handle)
            self._drag_pos = pos
            self.update()
            return
        if self._drawing:
            self._current = pos
            self.update()
            return
        if self._color is not None:
            return
        cursor = Qt.CursorShape.ArrowCursor
        for item in reversed(self.items):
            handle = item.hit_test(pos)
            if handle is not None:
                cursor = _HANDLE_CURSORS[handle]
                break
        self.setCursor(cursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._active_item is not None:
            self._active_item = None
            self._active_handle = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self._drawing and self._start is not None:
            rect = QRect(self._start, event.position().toPoint()).normalized()
            if rect.width() > 5 and rect.height() > 5 and self._color is not None:
                self.items.append(_ResizableRect(rect, self._color, self._annotation))
            self._drawing = False
            self._start = None
            self._current = None
            # The legacy dialog requires clicking the annotation button again before the next box.
            self._color = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._save()
        elif event.key() == Qt.Key.Key_Escape:
            self._cancel()
