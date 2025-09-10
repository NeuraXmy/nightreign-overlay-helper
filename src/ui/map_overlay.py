from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QSizePolicy,
)
from dataclasses import dataclass
from PyQt6.QtWidgets import QGraphicsDropShadowEffect
from PyQt6.QtGui import QColor, QPixmap, QImage
from PIL import Image
from datetime import timedelta
import time

from src.common import get_readable_timedelta
from src.ui.utils import set_widget_always_on_top


@dataclass
class MapOverlayUIState:
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None
    opacity: float | None = None
    visible: bool | None = None
    overlay_image: Image.Image | None = None
    clear_image: bool = False
    map_pattern_matching: bool | None = None
    map_pattern_match_time: float | None = None

    only_show_when_game_foreground: bool | None = None
    is_game_foreground: bool | None = None
    is_menu_opened: bool | None = None
    is_setting_opened: bool | None = None


class MapOverlayWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        set_widget_always_on_top(self)
        self.startTimer(50)

        self.label = QLabel(self)
        self.label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.map_pattern_match_time: float = 0.0
        self.map_pattern_matching: bool = False
        self.match_time_label = QLabel(self)
        self.match_time_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
        )
        shadow_effect = QGraphicsDropShadowEffect(self.match_time_label)
        shadow_effect.setBlurRadius(5)
        shadow_effect.setOffset(2, 2)
        shadow_effect.setColor(QColor(0, 0, 0, 160))
        self.match_time_label.setGraphicsEffect(shadow_effect)

        self.target_opacity = 1.0

        self.visible = True
        self.only_show_when_game_foreground = False
        self.is_game_foreground = False
        self.is_menu_opened = False
        self.is_setting_opened = False

        self.update_ui_state(
            MapOverlayUIState(
                w=10,
                h=10,
                opacity=0.0,
                visible=True,
            )
        )

    def set_image(self, img: Image.Image | None):
        if img is None:
            self.label.clear()
            return
        img = img.convert("RGBA").resize(
            (self.width(), self.height()), Image.Resampling.BICUBIC
        )
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        self.label.setPixmap(pixmap)

    def update_ui_state(self, state: MapOverlayUIState):
        if state.x is not None and state.y is not None:
            self.move(
                int(state.x / self.devicePixelRatio()),
                int(state.y / self.devicePixelRatio()),
            )
        if state.w is not None and state.h is not None:
            self.resize(
                int(state.w / self.devicePixelRatio()),
                int(state.h / self.devicePixelRatio()),
            )
        if state.opacity is not None:
            self.target_opacity = state.opacity
        if state.visible is not None:
            self.visible = state.visible
        if state.overlay_image is not None:
            self.set_image(state.overlay_image)
        if state.clear_image:
            self.set_image(None)
        if state.only_show_when_game_foreground is not None:
            self.only_show_when_game_foreground = state.only_show_when_game_foreground
        if state.is_game_foreground is not None:
            self.is_game_foreground = state.is_game_foreground
        if state.is_menu_opened is not None:
            self.is_menu_opened = state.is_menu_opened
        if state.is_setting_opened is not None:
            self.is_setting_opened = state.is_setting_opened
        if state.map_pattern_matching is not None:
            self.map_pattern_matching = state.map_pattern_matching
        if state.map_pattern_match_time is not None:
            self.map_pattern_match_time = state.map_pattern_match_time
        self.update()

    def timerEvent(self, event):
        self.label.setGeometry(0, 0, self.width(), self.height())
        self.match_time_label.setGeometry(
            0, 0, int(self.width() * 0.97), int(self.height() * 0.99)
        )

        if self.map_pattern_matching:
            spin_line = ["|", "/", "-", "\\"][int(time.time() * 4) % 4]
            self.match_time_label.setText(f"正在识别中... {spin_line}")
        elif self.map_pattern_match_time > 0:
            elapsed = time.time() - self.map_pattern_match_time
            self.match_time_label.setText(
                f"识别时间：{get_readable_timedelta(timedelta(seconds=elapsed))}前"
            )
        else:
            self.match_time_label.setText("")
        font_size = max(8, 24 * self.height() // 750)
        self.match_time_label.setStyleSheet(f"color: white; font-size: {font_size}px;")

        threshold = 0.01
        step = 0.6
        real_opacity = self.windowOpacity()
        dlt = self.target_opacity - real_opacity
        if abs(dlt) > threshold:
            real_opacity += dlt * step
            self.setWindowOpacity(real_opacity)
        elif 0 < abs(dlt) <= threshold:
            real_opacity = self.target_opacity
            self.setWindowOpacity(real_opacity)

        visible = self.visible and real_opacity > 0.01
        if self.only_show_when_game_foreground:
            visible = visible and (
                self.is_game_foreground or self.is_menu_opened or self.is_setting_opened
            )
        if visible and not self.isVisible():
            self.show()
        elif not visible and self.isVisible():
            self.hide()
