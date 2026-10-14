"""Separate, non-activating map controls that follow the unchanged map overlay."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer
from PyQt6.QtGui import QPaintEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLayout, QPushButton, QWidget
from qfluentwidgets import FluentIcon, Theme

from nightreign_overlay.plugins.map_detect.manual_filter import ManualFilterOverlay
from nightreign_overlay.plugins.map_detect.overlay import MapInfoOverlay
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayWindow


class MapControlsOverlay(OverlayWindow):
    """Own only the toolbar's input; the map retains its mouse passthrough behavior."""

    def __init__(
        self,
        source: MapInfoOverlay,
        manual_overlay: ManualFilterOverlay,
        tr: Callable[..., str],
        callbacks: dict[str, Callable],
    ) -> None:
        self.source = source
        self.manual_overlay = manual_overlay
        self.manual_filtering = False
        self._tr = tr
        # Position and appearance are derived from the map, never persisted independently.
        config = OverlayConfig("", {"input_mode": "locked"}, lambda *_: None)
        super().__init__(source.manager, config, tr("controls.title"), QSize(1, 1))
        self.row = QHBoxLayout(self)
        self.row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.row.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.recognize = QPushButton(tr("controls.recognize"), self)
        self.recognize.clicked.connect(callbacks["recognize"])
        self.row.addWidget(self.recognize)
        self.manual_filter = QPushButton(tr("controls.manual_filter"), self)
        self.manual_filter.clicked.connect(callbacks["manual_filter"])
        self.row.addWidget(self.manual_filter)
        self.candidate_group, self.candidate_index, self.previous_candidate, self.next_candidate = (
            self._group(tr("controls.candidates"), callbacks["previous_result"], callbacks["next_result"], tr)
        )
        self.row.addWidget(self.candidate_group)
        self.crystal_group, self.crystal_index, self.previous_crystal, self.next_crystal = self._group(
            tr("controls.crystals"), callbacks["previous_crystal"], callbacks["next_crystal"], tr
        )
        self.row.addWidget(self.crystal_group)
        self.row.addStretch()
        self._buttons = self.findChildren(QPushButton)
        self._appearance_scale: float | None = None
        for button in self._buttons:
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        source.installEventFilter(self)
        manual_overlay.installEventFilter(self)
        # Connect after the map's tick so opacity/visibility are copied after its fade step.
        source._timer.timeout.connect(self.sync_from_map)
        manual_overlay.visibilityChanged.connect(self.sync_from_map)
        source.config.scale.valueChanged.connect(self.sync_from_map)
        source.config.opacity.valueChanged.connect(self.sync_from_map)
        self.sync_from_map()

    def _group(
        self, title: str, previous: Callable, following: Callable, tr: Callable[..., str]
    ) -> tuple[QWidget, QLabel, QPushButton, QPushButton]:
        group = QWidget(self)
        row = QHBoxLayout(group)
        row.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(title, group))
        back = QPushButton(group)
        back.setIcon(FluentIcon.LEFT_ARROW.icon(Theme.DARK))
        back.setToolTip(tr("controls.previous"))
        back.clicked.connect(previous)
        row.addWidget(back)
        index = QLabel("#0/0", group)
        index.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(index)
        forward = QPushButton(group)
        forward.setIcon(FluentIcon.RIGHT_ARROW.icon(Theme.DARK))
        forward.setToolTip(tr("controls.next"))
        forward.clicked.connect(following)
        row.addWidget(forward)
        return group, index, back, forward

    def apply_window_mode(self) -> None:
        # A standalone tool window with no main-window parent never activates the main UI.
        # Keep it frameless even when the map uses the ordinary-window fallback.
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.manager.backend.configure_overlay_activation(int(self.winId()), True)
        self.update_visibility()

    def should_be_visible(self) -> bool:
        source = self.manual_overlay if self.manual_filtering else self.source
        return source.isVisible() and source.should_be_visible()

    def set_manual_filtering(self, filtering: bool) -> None:
        self.manual_filtering = filtering
        self.sync_from_map()

    def sync_from_map(self, *_: object) -> None:
        if self._disposing:
            return
        source = self.manual_overlay if self.manual_filtering else self.source
        scale = source.width() / 750
        if self._appearance_scale != scale:
            self._apply_control_scale(scale)
        total = len(self.source.overlay_images or [])
        index = self.source.map_pattern_idx + 1 if total and self.source.map_pattern_idx is not None else 0
        self.candidate_index.setText(f"#{index}/{total}")
        self.previous_candidate.setEnabled(total > 1)
        self.next_candidate.setEnabled(total > 1)
        self.recognize.setEnabled(not self.manual_filtering)
        self.manual_filter.setText(
            self._tr("controls.exit_filter") if self.manual_filtering else self._tr("controls.manual_filter")
        )
        self.candidate_group.setVisible(not self.manual_filtering)
        crystal_visible = not self.manual_filtering and self.source.crystal_layout_idx is not None
        self.crystal_group.setVisible(crystal_visible)
        if self.source.crystal_layout_idx is not None:
            # Index 0 is the legacy 'all points' layout; layouts 1..4 keep their existing numbering.
            self.crystal_index.setText(
                f"#{self.source.crystal_layout_idx}/{len(self.source.crystal_layout_imgs) - 1}"
            )
            self.crystal_index.setToolTip(
                self.source._tr("overlay.all") if self.source.crystal_layout_idx == 0 else ""
            )
        self.setFixedSize(source.width(), max(1, round(45 * scale)))
        self.row.activate()
        # frameGeometry includes the title bar in ordinary-window mode.
        self._move_to(QPoint(source.frameGeometry().left(), source.frameGeometry().bottom() + 1))
        self.setWindowOpacity(source.windowOpacity())
        self.update_visibility()

    def _apply_control_scale(self, scale: float) -> None:
        self._appearance_scale = scale
        font_size = max(1, round(13 * scale))
        self.setStyleSheet(
            f"QLabel {{ color: white; font-size: {font_size}px; background: transparent; }}"
            f"QPushButton {{ color: white; font-size: {font_size}px; background: #354557;"
            f" border: 1px solid #637489; border-radius: {round(4 * scale)}px;"
            f" padding: {round(4 * scale)}px {round(8 * scale)}px; }}"
            "QPushButton:hover { background: #486681; border-color: #92bde3; }"
            "QPushButton:pressed { background: #20344a; }"
            "QPushButton:disabled { color: #89929d; background: #2b3139; border-color: #454b53; }"
        )
        margin = round(8 * scale)
        # Round the outer height first: independently rounded child heights and
        # margins can exceed it by a pixel (e.g. at 85%) and clip the arrow buttons.
        available_height = max(1, round(45 * scale) - 2 * margin)
        control_height = min(max(1, round(29 * scale)), available_height)
        self.row.setContentsMargins(*([margin] * 4))
        self.row.setSpacing(round(8 * scale))
        for button in self._buttons:
            button.setIconSize(QSize(round(16 * scale), round(16 * scale)))
            button.setFixedHeight(control_height)
            wide = button in (self.recognize, self.manual_filter)
            button.setFixedWidth(max(1, round((90 if wide else 36) * scale)))
        for label in self.findChildren(QLabel):
            label.setFixedHeight(control_height)
        for group in (self.candidate_group, self.crystal_group):
            group.setFixedHeight(available_height)
            group.layout().setSpacing(round(6 * scale))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in (self.source, self.manual_overlay) and event.type() in (
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.Hide,
        ):
            QTimer.singleShot(0, self.sync_from_map)
        return super().eventFilter(watched, event)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Keep the toolbar background transparent, including ordinary-window fallback mode."""

    def dispose(self) -> None:
        if self._disposing:
            return
        self.source.removeEventFilter(self)
        self.manual_overlay.removeEventFilter(self)
        self.source._timer.timeout.disconnect(self.sync_from_map)
        self.manual_overlay.visibilityChanged.disconnect(self.sync_from_map)
        self.source.config.scale.valueChanged.disconnect(self.sync_from_map)
        self.source.config.opacity.valueChanged.disconnect(self.sync_from_map)
        super().dispose()
