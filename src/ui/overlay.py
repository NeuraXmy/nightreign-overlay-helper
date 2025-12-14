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
from src.ui.utils import set_widget_always_on_top


INITIAL_TEXT = f"{APP_FULLNAME} (右键打开菜单)"


@dataclass
class OverlayUIState:
    x: int | None = None
    y: int | None = None
    scale: float | None = None
    opacity: float | None = None
    draggable: bool | None = None
    visible: bool | None = None

    day_progress: float | None = None
    day_text: str | None = None

    rain_progress_visible: bool | None = None
    rain_progress: float | None = None
    rain_text: str | None = None

    art_progress_visible: bool | None = None
    art_progress: float | None = None
    art_text: str | None = None
    art_color: str | None = None

    set_x_to_center: bool = False
    map_pattern_match_text: str | None = None
    hide_text: bool | None = None

    only_show_when_game_foreground: bool | None = None
    is_game_foreground: bool | None = None
    is_menu_opened: bool | None = None
    is_setting_opened: bool | None = None


class OverlayWidget(QWidget):
    double_click_signal = pyqtSignal()
    right_click_signal = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool 
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        set_widget_always_on_top(self)
        self.startTimer(50)

        self.scale = 1.0
        
        self.layout: QVBoxLayout = QVBoxLayout(self)

        self.day_progress_layout = QHBoxLayout()
        self.day_progress_layout.setSpacing(1)
        self.day_pbs: list[QProgressBar] = []
        for i in range(4):
            length = Config.get().day_period_seconds[i]
            pb = QProgressBar()
            pb.setTextVisible(False)
            pb.setRange(0, 10000)
            pb.setMinimumWidth(10)
            self.day_pbs.append(pb)
            self.day_progress_layout.addWidget(pb)
            self.day_progress_layout.setStretchFactor(pb, length)
        self.layout.addLayout(self.day_progress_layout)

        self.day_text = ""
        self.map_pattern_match_text = ""
        self.day_label = QLabel()
        self.day_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shadow_effect = QGraphicsDropShadowEffect()
        shadow_effect.setBlurRadius(10)
        shadow_effect.setColor(QColor(0, 0, 0, 150)) 
        shadow_effect.setOffset(0, 0) 
        self.day_label.setGraphicsEffect(shadow_effect)
        self.layout.addWidget(self.day_label)

        self.rain_pb = QProgressBar()
        self.rain_pb.setTextVisible(False)
        self.rain_pb.setRange(0, 10000)
        self.layout.addWidget(self.rain_pb)

        self.rain_label = QLabel()
        self.rain_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shadow_effect = QGraphicsDropShadowEffect()
        shadow_effect.setBlurRadius(10)
        shadow_effect.setColor(QColor(0, 0, 0, 150)) 
        shadow_effect.setOffset(0, 0) 
        self.rain_label.setGraphicsEffect(shadow_effect)
        self.layout.addWidget(self.rain_label)

        self.art_pb = QProgressBar()
        self.art_pb.setTextVisible(False)
        self.art_pb.setRange(0, 10000)
        self.layout.addWidget(self.art_pb)
        self.art_color = "#ffffff"

        self.art_label = QLabel()
        self.art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shadow_effect = QGraphicsDropShadowEffect()
        shadow_effect.setBlurRadius(10)
        shadow_effect.setColor(QColor(0, 0, 0, 150))
        shadow_effect.setOffset(0, 0)
        self.art_label.setGraphicsEffect(shadow_effect)
        self.layout.addWidget(self.art_label)

        self.layout.addStretch()
        
        self.drag_position = QPoint()
        self.draggable = False

        self.day_pb_css = Config.get().day_progress_css
        self.day_text_css = Config.get().day_text_css
        self.rain_pb_css = Config.get().in_rain_progress_css
        self.rain_text_css = Config.get().in_rain_text_css
        self.art_pb_css = Config.get().art_progress_css
        self.art_text_css = Config.get().art_text_css

        self.visible = True
        self.only_show_when_game_foreground = False
        self.is_game_foreground = False
        self.is_menu_opened = False
        self.is_setting_opened = False

        self.rain_progress_visible = False
        self.art_progress_visible = False
        self.hide_text = False 
       
        self.update_ui_state(OverlayUIState(
            visible=True,
            scale=1.0,
            opacity=0.6,
            draggable=False,
            day_progress=0,
            day_text=INITIAL_TEXT,
            map_pattern_match_text="",
            rain_progress=0,
            rain_text="",
            rain_progress_visible=False,
            art_progress=0,
            art_text="",
            art_progress_visible=False,
            hide_text=False,
        ))

    def mousePressEvent(self, event: QMouseEvent):
        if self.draggable and event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        if event.button() == Qt.MouseButton.RightButton:
            self.right_click_signal.emit()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.draggable and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_click_signal.emit()
            event.accept()
    
    def _set_draggable(self, draggable: bool):
        self.draggable = draggable
        if draggable:
            self.setStyleSheet("background: #333;")
            info("Overlay: Draggable mode ON")
        else:
            self.setStyleSheet("")
            info("Overlay: Draggable mode OFF")

    def _apply_scale(self, scale: float):
        self.scale = scale
        width = int(400 * scale)
        height = int(140 * scale)
        self.setFixedSize(width, height)

        font_size = int(14 * scale)
        self.day_label.setStyleSheet(self.day_text_css.replace("{font_size}", str(font_size)))
        self.rain_label.setStyleSheet(self.rain_text_css.replace("{font_size}", str(font_size)))
        self.art_label.setStyleSheet(self.art_text_css.replace("{font_size}", str(font_size)))

        pb_height = int(16 * scale)
        pb_border_radius = int(pb_height / 5)

        for i in range(4):
            self.day_pbs[i].setFixedHeight(pb_height)
            self.day_pbs[i].setStyleSheet(self.day_pb_css.replace("{border_radius}", str(pb_border_radius)))

        self.rain_pb.setFixedHeight(pb_height)
        self.rain_pb.setStyleSheet(self.rain_pb_css.replace("{border_radius}", str(pb_border_radius)))

        self.art_pb.setFixedHeight(pb_height)
        self.art_pb.setStyleSheet(self.art_pb_css.replace("{border_radius}", str(pb_border_radius)).replace("{color}", self.art_color))

    def update_ui_state(self, state: OverlayUIState):
        if state.x is not None and state.y is not None:
            self.move(state.x, state.y)
        if state.set_x_to_center:
            screen = QApplication.primaryScreen()
            screen_geometry = screen.geometry()
            new_x = (screen_geometry.width() - self.width()) // 2
            self.move(new_x, self.y())
        if state.scale is not None:
            self._apply_scale(state.scale)
        if state.opacity is not None:
            self.setWindowOpacity(state.opacity)
        if state.day_progress is not None:
            for i in range(4):
                progress = min(1, max(0, (state.day_progress - i)))
                self.day_pbs[i].setValue(int(progress * self.day_pbs[i].maximum()))
        if state.day_text is not None:
            self.day_text = state.day_text
            self.day_label.setText(self.day_text + self.map_pattern_match_text 
                               if self.day_text != INITIAL_TEXT else INITIAL_TEXT)
        if state.map_pattern_match_text is not None:
            self.map_pattern_match_text = state.map_pattern_match_text
            self.day_label.setText(self.day_text + self.map_pattern_match_text
                                 if self.day_text != INITIAL_TEXT else INITIAL_TEXT)
        if state.draggable is not None:
            self._set_draggable(state.draggable)
        if state.visible is not None:
            self.visible = state.visible
        if state.rain_progress is not None:
            self.rain_pb.setValue(int(state.rain_progress * self.rain_pb.maximum()))
        if state.rain_text is not None:
            self.rain_label.setText(state.rain_text)
        if state.rain_progress_visible is not None:
            self.rain_progress_visible = state.rain_progress_visible
        if state.art_progress is not None:
            self.art_pb.setValue(int(state.art_progress * self.art_pb.maximum()))
        if state.art_text is not None:
            self.art_label.setText(state.art_text)
        if state.art_progress_visible is not None:
            self.art_progress_visible = state.art_progress_visible
        if state.art_color is not None:
            self.art_color = state.art_color
            self._apply_scale(self.scale) 
        if state.only_show_when_game_foreground is not None:
            self.only_show_when_game_foreground = state.only_show_when_game_foreground
        if state.is_game_foreground is not None:
            self.is_game_foreground = state.is_game_foreground
        if state.is_menu_opened is not None:
            self.is_menu_opened = state.is_menu_opened
        if state.is_setting_opened is not None:
            self.is_setting_opened = state.is_setting_opened
        if state.hide_text is not None:
            self.hide_text = state.hide_text
        self.update()

    def timerEvent(self, event):
        visible = self.visible and self.windowOpacity() > 0.01
        if self.only_show_when_game_foreground:
            visible = visible and (self.is_game_foreground or self.is_menu_opened or self.is_setting_opened)
        if visible and not self.isVisible():
            self.show()
        elif not visible and self.isVisible():
            self.hide()
        
        if self.hide_text:
            self.day_label.hide()
        else:
            self.day_label.show()

        if self.hide_text or not self.rain_progress_visible:
            self.rain_label.hide()
        else:
            self.rain_label.show()

        if self.rain_progress_visible:
            self.rain_pb.show()
        else:
            self.rain_pb.hide()

        if self.hide_text or not self.art_progress_visible:
            self.art_label.hide()
        else:
            self.art_label.show()

        if self.art_progress_visible:
            self.art_pb.show()
        else:
            self.art_pb.hide()

