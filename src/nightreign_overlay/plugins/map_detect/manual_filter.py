"""Interactive transparent overlay for manually narrowing map candidates."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PIL import Image
from PyQt6.QtCore import QPoint, QRect, QSignalBlocker, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QIcon, QImage, QPaintEvent, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nightreign_overlay.plugins.map_detect.manual_catalog import (
    EMPTY,
    UNSET,
    ManualFilterCatalog,
    PoiChoice,
    Subicon,
)
from nightreign_overlay.plugins.map_detect.map_info import Position
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayManager, OverlayWindow


class ManualFilterOverlay(OverlayWindow):
    """Cover the calibrated map region with interactive manual-filter controls."""

    earthShiftingChanged = pyqtSignal(object)
    nightlordChanged = pyqtSignal(object)
    visibilityChanged = pyqtSignal(bool)
    poiChoiceChanged = pyqtSignal(object, object)
    autoRecognizeRequested = pyqtSignal(object)
    applyRequested = pyqtSignal()

    def __init__(
        self,
        manager: OverlayManager,
        tr: Callable[..., str],
        earth_shiftings: Sequence[tuple[int, str]],
        nightlords: Sequence[tuple[int, str]],
    ) -> None:
        # OverlayWindow.__init__ calls should_be_visible(), so these must exist first.
        self._map_open = False
        self._capture_hidden = False
        config = OverlayConfig("", {"input_mode": "locked"}, lambda *_: None)
        super().__init__(manager, config, tr("manual_filter.title"), QSize(1, 1))
        self._tr = tr
        self.catalog: ManualFilterCatalog | None = None
        self.earth_shifting: int | None = None
        self.nightlord: int | None = None
        self.explicit_choices: dict[Position, PoiChoice] = {}
        self.inferred_choices: dict[Position, PoiChoice] = {}
        self.position_buttons: dict[Position, QPushButton] = {}
        self.badge_buttons: dict[Position, QPushButton] = {}
        self._visible_positions: set[Position] = set()
        self._recognizing_pos: Position | None = None
        self._popup: QWidget | None = None

        self.earth_shifting_combo = QComboBox(self)
        self.earth_shifting_combo.setPlaceholderText(tr("manual_filter.earth_shifting"))
        for earth_shifting, name in earth_shiftings:
            self.earth_shifting_combo.addItem(name, earth_shifting)
        self.earth_shifting_combo.setCurrentIndex(-1)
        self.earth_shifting_combo.currentIndexChanged.connect(self._on_earth_shifting_changed)

        self.nightlord_combo = QComboBox(self)
        self.nightlord_combo.addItem(tr("manual_filter.all_nightlords"), None)
        for nightlord, name in nightlords:
            self.nightlord_combo.addItem(name, nightlord)
        self.nightlord_combo.currentIndexChanged.connect(self._on_nightlord_changed)

        combo_style = (
            "QComboBox { color: white; background: rgba(53, 69, 87, 235);"
            " border: 1px solid #92bde3; border-radius: 4px; padding: 2px 24px 2px 8px; }"
            "QComboBox:hover { background: rgba(72, 102, 129, 245); }"
            "QComboBox QAbstractItemView { color: white; background: #354557;"
            " selection-background-color: #486681; }"
        )
        self.earth_shifting_combo.setStyleSheet(combo_style)
        self.nightlord_combo.setStyleSheet(combo_style)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(QLabel(tr("manual_filter.earth_shifting"), self))
        row.addWidget(self.earth_shifting_combo)
        row.addWidget(QLabel(tr("manual_filter.nightlord"), self))
        row.addWidget(self.nightlord_combo)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 6, 6)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addLayout(row)
        layout.addStretch(1)

        self.status_label = QLabel("", self)
        self.status_label.hide()
        self.apply_button = QPushButton(tr("manual_filter.apply_now"), self)
        self.apply_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.apply_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_button.setStyleSheet(
            "QPushButton { color: white; background: rgba(53, 69, 87, 235); border: 1px solid #92bde3;"
            " border-radius: 4px; padding: 3px 8px; font-weight: bold; }"
            "QPushButton:hover { background: rgba(72, 102, 129, 245); }"
            "QPushButton:pressed { background: #20344a; }"
        )
        self.apply_button.clicked.connect(lambda _checked=False: self.applyRequested.emit())
        self.apply_button.hide()
        self._apply_control_size()

    # Catalog and filter state ------------------------------------------------------------------

    def set_catalog(self, catalog: ManualFilterCatalog) -> None:
        if self.catalog is catalog:
            return
        self.catalog = catalog
        for pos in catalog.all_positions():
            position = QPushButton("+", self)
            position.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            position.setCursor(Qt.CursorShape.PointingHandCursor)
            position.clicked.connect(lambda _checked=False, p=pos: self._show_base_popup(p))
            position.hide()
            self.position_buttons[pos] = position

            badge = QPushButton("+", self)
            badge.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            badge.setCursor(Qt.CursorShape.PointingHandCursor)
            badge.clicked.connect(lambda _checked=False, p=pos: self._show_badge_popup(p))
            badge.hide()
            self.badge_buttons[pos] = badge
        self._layout_position_buttons()

    def reset_selection(self) -> None:
        """Restore entry defaults without treating the reset as user input."""
        earth_blocker = QSignalBlocker(self.earth_shifting_combo)
        nightlord_blocker = QSignalBlocker(self.nightlord_combo)
        self.earth_shifting_combo.setCurrentIndex(-1)
        self.nightlord_combo.setCurrentIndex(0)
        self.earth_shifting = None
        self.nightlord = None
        del earth_blocker, nightlord_blocker
        self.clear_poi_choices()
        self.refresh_positions()
        self.show_select_earth_shifting()

    def clear_poi_choices(self) -> None:
        self.explicit_choices.clear()
        self.inferred_choices.clear()
        self._recognizing_pos = None
        self.clear_status()
        self.close_popup()
        self._refresh_buttons()

    def set_filter_state(
        self,
        explicit: dict[Position, PoiChoice],
        inferred: dict[Position, PoiChoice],
    ) -> None:
        self.explicit_choices = dict(explicit)
        self.inferred_choices = dict(inferred)
        self._recognizing_pos = None
        self._refresh_buttons()

    def refresh_positions(self) -> None:
        if self.catalog is None or self.earth_shifting is None:
            self._visible_positions = set()
        else:
            self._visible_positions = set(self.catalog.positions(self.earth_shifting, self.nightlord))
        self._refresh_buttons()

    def set_auto_recognizing(self, pos: Position | None) -> None:
        self._recognizing_pos = pos
        self._refresh_buttons()

    def show_select_earth_shifting(self) -> None:
        self._show_status(self._tr("manual_filter.select_earth_shifting"), "#ff4242")

    def show_candidate_count(self, count: int, can_apply: bool = False) -> None:
        self._show_status(self._tr("manual_filter.remaining_candidates", count=count), "white", can_apply)

    def show_no_match(self) -> None:
        self._show_status(self._tr("manual_filter.no_match"), "#ff4242")

    def _show_status(self, text: str, color: str, can_apply: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"color: {color}; background: rgba(0, 0, 0, 150); padding: 3px; font-weight: bold;"
        )
        self.status_label.show()
        self.status_label.raise_()
        self.apply_button.setVisible(can_apply)
        self.apply_button.raise_()
        self._layout_status()

    def clear_status(self) -> None:
        self.status_label.hide()
        self.apply_button.hide()

    # Visibility --------------------------------------------------------------------------------

    def set_map_open(self, open_: bool) -> None:
        """Temporarily hide with the map while retaining the current choices."""
        if open_ == self._map_open:
            return
        self._map_open = open_
        self.update_visibility()
        self.visibilityChanged.emit(self.should_be_visible())

    @property
    def map_open(self) -> bool:
        return self._map_open

    def set_capture_hidden(self, hidden: bool) -> None:
        if hidden == self._capture_hidden:
            return
        self._capture_hidden = hidden
        self.update_visibility()
        self.visibilityChanged.emit(self.should_be_visible())

    def should_be_visible(self) -> bool:
        return self._map_open and not self._capture_hidden and super().should_be_visible()

    # Choices and popup --------------------------------------------------------------------------

    def _show_base_popup(self, pos: Position) -> None:
        if self.catalog is None or self.earth_shifting is None or pos == self._recognizing_pos:
            return
        options: list[tuple[str | None, Image.Image | None, Callable[[], None]]] = [
            (
                self._tr("manual_filter.auto_recognize"),
                None,
                lambda: self.autoRecognizeRequested.emit(pos),
            )
        ]
        for base in self.catalog.base_options(
            self.earth_shifting, self.nightlord, self.explicit_choices, pos
        ):
            if base == EMPTY:
                options.append((self._tr("manual_filter.empty"), None, lambda: self._choose_base(pos, EMPTY)))
            else:
                options.append(
                    (None, self.catalog.base_image(base), lambda b=base: self._choose_base(pos, b))
                )
        self._show_popup(self.position_buttons[pos], options)

    def _show_badge_popup(self, pos: Position) -> None:
        if self.catalog is None or self.earth_shifting is None:
            return
        displayed = self._display_choice(pos)
        if displayed is None or displayed.base == EMPTY:
            return
        options: list[tuple[str | None, Image.Image | None, Callable[[], None]]] = []
        for subicon in self.catalog.subicon_options(
            self.earth_shifting, self.nightlord, self.explicit_choices, pos, displayed.base
        ):
            if subicon is None:
                options.append(
                    (
                        self._tr("manual_filter.empty"),
                        None,
                        lambda: self._choose_badge(pos, None),
                    )
                )
            else:
                options.append(
                    (None, self.catalog.subicon_image(subicon), lambda s=subicon: self._choose_badge(pos, s))
                )
        self._show_popup(self.badge_buttons[pos], options)

    def _choose_base(self, pos: Position, base: int) -> None:
        self.poiChoiceChanged.emit(pos, PoiChoice(base, None if base == EMPTY else UNSET))

    def _choose_badge(self, pos: Position, subicon: Subicon) -> None:
        displayed = self._display_choice(pos)
        if displayed is not None:
            self.poiChoiceChanged.emit(pos, PoiChoice(displayed.base, subicon))

    def _show_popup(
        self,
        anchor: QPushButton,
        options: list[tuple[str | None, Image.Image | None, Callable[[], None]]],
    ) -> None:
        self.close_popup()
        popup = QFrame(None, Qt.WindowType.Popup)
        popup.setStyleSheet(
            "QFrame { background: #263442; border: 1px solid #74899f; }"
            "QPushButton { color: white; background: #3a4d60; border: 1px solid #687f96; padding: 4px; }"
            "QPushButton:hover { background: #54728e; }"
        )
        grid = QGridLayout(popup)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(4)
        for index, (text, image, callback) in enumerate(options):
            button = QPushButton(text or "", popup)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(80 if text else 42, 42)
            if image is not None:
                button.setIcon(QIcon(_pil_pixmap(image)))
                button.setIconSize(QSize(34, 34))
            button.clicked.connect(lambda _checked=False, cb=callback: self._popup_choice(cb))
            grid.addWidget(button, index // 4, index % 4)
        popup.adjustSize()
        popup.move(anchor.mapToGlobal(QPoint(0, anchor.height())))
        self._popup = popup
        popup.show()

    def _popup_choice(self, callback: Callable[[], None]) -> None:
        self.close_popup()
        callback()

    def close_popup(self) -> None:
        if self._popup is not None:
            self._popup.close()
            self._popup.deleteLater()
            self._popup = None

    # Rendering and geometry --------------------------------------------------------------------

    def _display_choice(self, pos: Position) -> PoiChoice | None:
        return self.inferred_choices.get(pos, self.explicit_choices.get(pos))

    def _refresh_buttons(self) -> None:
        if self.catalog is None:
            return
        for pos, button in self.position_buttons.items():
            visible = pos in self._visible_positions
            button.setVisible(visible)
            badge = self.badge_buttons[pos]
            if not visible:
                badge.hide()
                continue
            recognizing = pos == self._recognizing_pos
            choice = self._display_choice(pos)
            button.setEnabled(not recognizing)
            button.setIcon(QIcon())
            button.setText("…" if recognizing else "+" if choice is None else "")
            button.setStyleSheet(_round_style(choice is None, 15))
            if choice is not None and choice.base != EMPTY:
                button.setIcon(QIcon(_pil_pixmap(self.catalog.base_image(choice.base))))
                button.setIconSize(button.size() - QSize(4, 4))

            show_badge = False
            if choice is not None and choice.base != EMPTY and self.earth_shifting is not None:
                options = self.catalog.subicon_options(
                    self.earth_shifting, self.nightlord, self.explicit_choices, pos, choice.base
                )
                show_badge = any(subicon is not None for subicon in options)
            badge.setVisible(show_badge)
            if show_badge:
                badge.setIcon(QIcon())
                badge.setText("+")
                badge.setStyleSheet(_round_style(choice.subicon is UNSET, 8))
                if choice.subicon is None:
                    badge.setText("")
                elif choice.subicon is not UNSET:
                    badge.setText("")
                    badge.setIcon(QIcon(_pil_pixmap(self.catalog.subicon_image(choice.subicon))))
                    badge.setIconSize(badge.size() - QSize(2, 2))
                badge.raise_()
        self.status_label.raise_()
        self.apply_button.raise_()

    def _apply_control_size(self) -> None:
        scale = max(0.1, self.width() / 750)
        height = max(1, round(35 * scale))
        font = self.font()
        font.setPixelSize(max(1, round(16 * scale)))
        for label in self.findChildren(QLabel):
            label.setFont(font)
        self.apply_button.setFont(font)
        for combo in (self.earth_shifting_combo, self.nightlord_combo):
            combo.setFont(font)
            content_width = max(
                (combo.fontMetrics().horizontalAdvance(combo.itemText(i)) for i in range(combo.count())),
                default=0,
            )
            combo.setFixedSize(max(round(216 * scale), content_width + round(58 * scale)), height)
        self._layout_position_buttons()
        self._layout_status()

    def _layout_position_buttons(self) -> None:
        scale = max(0.1, self.width() / 750)
        diameter = max(9, round(38 * scale))
        badge_size = max(7, round(18 * scale))
        badge_offset = max(1, round(3 * scale))
        for pos, button in self.position_buttons.items():
            x, y = round(pos[0] * scale), round(pos[1] * scale)
            button.setGeometry(x - diameter // 2, y - diameter // 2, diameter, diameter)
            badge = self.badge_buttons[pos]
            badge.setGeometry(
                x + diameter // 2 - badge_size + badge_offset,
                y + diameter // 2 - badge_size + badge_offset,
                badge_size,
                badge_size,
            )

    def _layout_status(self) -> None:
        self.status_label.adjustSize()
        scale = max(0.1, self.width() / 750)
        margin = max(4, round(8 * scale))
        x = max(0, self.width() - self.status_label.width() - margin)
        y = max(0, self.height() - self.status_label.height() - margin)
        self.status_label.move(x, y)
        self.apply_button.adjustSize()
        self.apply_button.setFixedHeight(self.status_label.height())
        self.apply_button.move(
            max(0, x - self.apply_button.width() - round(6 * scale)),
            y,
        )

    def _on_earth_shifting_changed(self, index: int) -> None:
        earth_shifting = self.earth_shifting_combo.itemData(index)
        if earth_shifting == self.earth_shifting:
            return
        self.earth_shifting = earth_shifting
        self.clear_status()
        self.earthShiftingChanged.emit(earth_shifting)

    def _on_nightlord_changed(self, index: int) -> None:
        nightlord = self.nightlord_combo.itemData(index)
        if nightlord == self.nightlord:
            return
        self.nightlord = nightlord
        self.clear_status()
        self.nightlordChanged.emit(nightlord)

    def set_map_region(self, rect: QRect) -> None:
        """Match the calibrated map region's device-pixel coordinates."""
        screen = next(
            (
                candidate
                for candidate in QGuiApplication.screens()
                if 0
                <= (rect.x() - candidate.geometry().x()) / candidate.devicePixelRatio()
                < candidate.geometry().width()
                and 0
                <= (rect.y() - candidate.geometry().y()) / candidate.devicePixelRatio()
                < candidate.geometry().height()
            ),
            QGuiApplication.primaryScreen(),
        )
        ratio = screen.devicePixelRatio() if screen is not None else 1.0
        origin = screen.geometry().topLeft() if screen is not None else QPoint()
        self.set_base_size(QSize(max(1, int(rect.width() / ratio)), max(1, int(rect.height() / ratio))))
        self._apply_control_size()
        self._move_to(
            QPoint(
                origin.x() + int((rect.x() - origin.x()) / ratio),
                origin.y() + int((rect.y() - origin.y()) / ratio),
            )
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        """Keep the full-window background transparent in every presentation mode."""

    def dispose(self) -> None:
        self.close_popup()
        super().dispose()


def _pil_pixmap(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    return QPixmap.fromImage(QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888).copy())


def _round_style(unset: bool, radius: int) -> str:
    background = "rgba(255, 255, 255, 80)" if unset else "rgba(100, 100, 100, 85)"
    color = "black" if unset else "white"
    return (
        f"QPushButton {{ background: {background}; color: {color}; border: 1px solid rgba(0,0,0,210);"
        f" border-radius: {radius}px; font-weight: bold; padding: 0; }}"
        "QPushButton:hover { border: 2px solid white; }"
        "QPushButton:disabled { color: white; background: rgba(90,90,90,95); }"
    )
