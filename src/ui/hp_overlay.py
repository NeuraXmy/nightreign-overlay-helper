from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QProgressBar, QLabel, QHBoxLayout, QSizePolicy
)
from PyQt6.QtGui import QMouseEvent, QKeySequence, QKeyEvent
from dataclasses import dataclass, field
from PyQt6.QtWidgets import QGraphicsDropShadowEffect
from PyQt6.QtGui import QColor

from src.common import APP_FULLNAME, APP_AUTHOR
from src.config import Config
from src.logger import info, warning, error
from src.ui.utils import set_widget_always_on_top, mss_region_to_qt_region


@dataclass
class HpOverlayUIState:
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None
    visible: bool | None = None

    only_show_when_game_foreground: bool | None = None
    is_game_foreground: bool | None = None
    is_menu_opened: bool | None = None
    is_setting_opened: bool | None = None


class HpOverlayWidget(QWidget):
    LINE_WIDTH = 3
    LINE_HEIGHT = 7

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

        self.hpbar_region: tuple[int] = (0, 0, 10, 10)

        self.label = QLabel(self)
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.percent20line = QLabel(self)
        self.percent20line.setStyleSheet("background-color: white;")

        self.percent85line = QLabel(self)
        self.percent85line.setStyleSheet("background-color: white;")
        
        self.percent100line = QLabel(self)
        self.percent100line.setStyleSheet("background-color: white;")

        self.visible = True
        self.only_show_when_game_foreground = False
        self.is_game_foreground = False
        self.is_menu_opened = False
        self.is_setting_opened = False

        self.update_ui_state(HpOverlayUIState(visible=False))
        
    def update_ui_state(self, state: HpOverlayUIState):
        if state.x is not None:
            self.hpbar_region = mss_region_to_qt_region((state.x, state.y, state.w, state.h))
        if state.visible is not None:
            self.visible = state.visible
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
        line_height = int(self.LINE_HEIGHT / self.devicePixelRatio())
        line_width = int(self.LINE_WIDTH / self.devicePixelRatio())

        cfg = Config.get()

        x, y, w, h = self.hpbar_region
        y -= line_height  # 移动到血条上方
        h = line_height
        self.setGeometry(x, y, w, h)

        self.percent20line.move(int(self.width() * cfg.hpbar_low_hp_marker) - line_width // 2, 0)
        self.percent20line.resize(line_width, self.height())

        self.percent85line.move(int(self.width() * cfg.hpbar_high_hp_marker) - line_width // 2, 0)
        self.percent85line.resize(line_width, self.height())
        
        self.percent100line.move(self.width() - line_width, 0)
        self.percent100line.resize(line_width, self.height())

        visible = self.visible and self.windowOpacity() > 0.01
        if self.only_show_when_game_foreground:
            visible = visible and (self.is_game_foreground or self.is_menu_opened or self.is_setting_opened)
        if visible and not self.isVisible():
            self.show()
        elif not visible and self.isVisible():
            self.hide()

        