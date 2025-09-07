from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QProgressBar, QLabel, QHBoxLayout, QSizePolicy
)
from PyQt6.QtGui import QMouseEvent, QKeySequence, QKeyEvent
from dataclasses import dataclass, field
from PyQt6.QtWidgets import QGraphicsDropShadowEffect
from PyQt6.QtGui import QColor, QPixmap, QImage
from PIL import Image

from src.common import APP_FULLNAME, APP_AUTHER, GAME_WINDOW_TITLE
from src.config import Config
from src.logger import info, warning, error
from src.ui.utils import set_widget_always_on_top, is_window_in_foreground


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

    only_show_when_game_foreground: bool | None = None
    is_game_foreground: bool | None = None
    is_menu_opened: bool | None = None
    is_setting_opened: bool | None = None



class MapOverlayWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        set_widget_always_on_top(self)
        self.startTimer(50)

        self.layout: QVBoxLayout = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.label)

        self.target_opacity = 1.0
        self.real_opacity = 1.0

        self.visible = True
        self.only_show_when_game_foreground = False
        self.is_game_foreground = False
        self.is_menu_opened = False
        self.is_setting_opened = False

        self.update_ui_state(MapOverlayUIState(
            w=10,
            h=10,
            opacity=0.0,
            visible=True,
        ))

    def set_image(self, img: Image.Image | None):
        if img is None:
            self.label.clear()
            return
        img = img.convert("RGBA").resize((self.width(), self.height()), Image.Resampling.BICUBIC)
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        self.label.setPixmap(pixmap)
        
    def update_ui_state(self, state: MapOverlayUIState):
        if state.x is not None and state.y is not None:
            self.move(
                int(state.x / self.devicePixelRatio()),
                int(state.y / self.devicePixelRatio())
            )
        if state.w is not None and state.h is not None:
            self.resize(
                int(state.w / self.devicePixelRatio()),
                int(state.h / self.devicePixelRatio())
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
        self.update()


    def timerEvent(self, event):
        threshold = 0.01
        step = 0.6
        dlt = self.target_opacity - self.real_opacity
        if abs(dlt) > threshold:
            self.real_opacity += dlt * step
            self.setWindowOpacity(self.real_opacity)
        elif 0 < abs(dlt) <= threshold:
            self.real_opacity = self.target_opacity
            self.setWindowOpacity(self.real_opacity)

        visible = self.visible and self.real_opacity > 0.01
        if self.only_show_when_game_foreground:
            visible = visible and (self.is_game_foreground or self.is_menu_opened or self.is_setting_opened)
        if visible and not self.isVisible():
            self.show()
        elif not visible and self.isVisible():
            self.hide()

        