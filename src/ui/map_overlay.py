from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QProgressBar, 
    QLabel, QHBoxLayout, QSizePolicy, QStackedLayout,
)
from PyQt6.QtGui import QMouseEvent, QKeySequence, QKeyEvent
from dataclasses import dataclass, field
from PyQt6.QtWidgets import QGraphicsDropShadowEffect
from PyQt6.QtGui import QColor, QPixmap, QImage
from PIL import Image, ImageDraw
import os
from datetime import datetime, timedelta
import time
import glob

from src.common import get_readable_timedelta, get_data_path, load_yaml
from src.config import Config
from src.logger import info, warning, error
from src.ui.utils import set_widget_always_on_top, is_window_in_foreground, mss_region_to_qt_region
from src.detector.utils import draw_text


@dataclass
class MapOverlayUIState:
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None
    opacity: float | None = None
    visible: bool | None = None
    overlay_image: Image.Image | None = None
    display_crystal_layout: bool | None = None
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
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        set_widget_always_on_top(self)
        self.startTimer(50)

        self.label = QLabel(self)
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setScaledContents(True)

        self.crystal_layout_idx: int | None = None
        self.init_crystal_layout_imgs()

        self.crystal_layout_label = QLabel(self)
        self.crystal_layout_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.crystal_layout_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crystal_layout_label.setScaledContents(True)

        self.map_pattern_match_time: float = 0.0
        self.map_pattern_matching: bool = False
        self.match_time_label = QLabel(self)
        self.match_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
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

        self.update_ui_state(MapOverlayUIState(
            w=10,
            h=10,
            opacity=0.0,
            visible=True,
        ))

    def init_crystal_layout_imgs(self):
        def load_pil_img(path: str, size: tuple[int, int], alpha: float) -> Image.Image:
            if not os.path.isfile(path):
                error(f"Failed to open image file: {path}")
            icon = Image.open(path).convert("RGBA")
            icon = icon.resize(size, Image.Resampling.BICUBIC)
            if alpha < 1.0:
                r, g, b, a = icon.split()
                a = a.point(lambda p: int(p * alpha))
                icon = Image.merge('RGBA', (r, g, b, a))
            return icon
        
        MAP_SIZE = (750, 750)
        ICON_SIZE = (MAP_SIZE[0] // 25, MAP_SIZE[1] // 25)
        ICON_ALPHA = 0.8
        SPEC_PATTERN_ICON_SIZE = (MAP_SIZE[0] // 20, MAP_SIZE[1] // 20)
        SPEC_PATTERN_ICON_ALPHA = 0.8

        self.crystal_layout_imgs = []

        data = load_yaml(get_data_path("crystal.yaml"))

        crystals, underground_crystals = data['crystals'], data['underground_crystals']
        for pattern in data['patterns']:
            is_main = set(pattern['initial']) == set(crystals.keys()) | set(underground_crystals.keys())

            size = SPEC_PATTERN_ICON_SIZE if not is_main else ICON_SIZE
            alpha = SPEC_PATTERN_ICON_ALPHA if not is_main else ICON_ALPHA
            icon = load_pil_img(get_data_path("icons/crystal/crystal.png"), size, alpha)
            icon_later = load_pil_img(get_data_path("icons/crystal/later_crystal.png"), size, alpha)
            icon_underground = load_pil_img(get_data_path("icons/crystal/underground_crystal.png"), size, alpha)

            img = Image.new("RGBA", MAP_SIZE, (0, 0, 0, 0))
            def draw_crystal(idx: int, later: bool):
                if later: 
                    icon_img = icon_later
                elif idx in underground_crystals:
                    icon_img = icon_underground
                else:
                    icon_img = icon
                x_ratio, y_ratio = underground_crystals[idx] if idx in underground_crystals else crystals[idx]
                x = int(x_ratio * MAP_SIZE[0]) - icon_img.width // 2
                y = int(y_ratio * MAP_SIZE[1]) - icon_img.height // 2
                img.alpha_composite(icon_img, (x, y))

            for idx in pattern['initial']:
                draw_crystal(idx, later=False)
            for idx in pattern['later']:
                draw_crystal(idx, later=True)

            # 图片正下方中间绘制图例
            sx = MAP_SIZE[0] * 0.25
            sy = MAP_SIZE[1] * 0.87
            if not is_main:
                img.alpha_composite(icon, (int(sx), int(sy)))
                draw_text(img, (sx + ICON_SIZE[0] + 5, sy), "水晶点位", 20, color=(255, 255, 255, 220), outline_width=2, align='lt')
                img.alpha_composite(icon_underground, (int(sx), int(sy + ICON_SIZE[1])))
                draw_text(img, (sx + ICON_SIZE[0] + 5, sy + ICON_SIZE[1]), "地下水晶点位", 20, color=(255, 255, 255, 220), outline_width=2, align='lt')
                img.alpha_composite(icon_later, (int(sx), int(sy + 2 * (ICON_SIZE[1]))))
                draw_text(img, (sx + ICON_SIZE[0] + 5, sy + 2 * (ICON_SIZE[1])), "额外水晶点位", 20, color=(255, 255, 255, 220), outline_width=2, align='lt')
            else:
                img.alpha_composite(icon, (int(sx), int(sy + ICON_SIZE[1])))
                draw_text(img, (sx + ICON_SIZE[0] + 5, sy + ICON_SIZE[1]), "水晶点位", 20, color=(255, 255, 255, 220), outline_width=2, align='lt')
                img.alpha_composite(icon_underground, (int(sx), int(sy + 2 * (ICON_SIZE[1]))))
                draw_text(img, (sx + ICON_SIZE[0] + 5, sy + 2 * (ICON_SIZE[1])), "地下水晶点位", 20, color=(255, 255, 255, 220), outline_width=2, align='lt')
                
            self.crystal_layout_imgs.append(img)

    def set_image(self, img: Image.Image | None):
        if img is None:
            self.label.clear()
            return
        img = img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        pixmap.setDevicePixelRatio(self.devicePixelRatio())
        self.label.setPixmap(pixmap)

    def update_crystal_layout(self):
        if self.crystal_layout_idx is None:
            self.crystal_layout_label.clear()
            return
        img = self.crystal_layout_imgs[self.crystal_layout_idx]
        img = img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        pixmap.setDevicePixelRatio(self.devicePixelRatio())
        self.crystal_layout_label.setPixmap(pixmap)

    def update_ui_state(self, state: MapOverlayUIState):
        if state.x is not None:
            region = mss_region_to_qt_region((state.x, state.y, state.w, state.h))
            self.setGeometry(*region)
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
        if state.display_crystal_layout is not None:
            self.crystal_layout_idx = 0 if state.display_crystal_layout else None
            self.update_crystal_layout()
        self.update()

    def timerEvent(self, event):
        self.label.setGeometry(0, 0, self.width(), self.height())
        self.crystal_layout_label.setGeometry(0, 0, self.width(), self.height())
        self.match_time_label.setGeometry(0, 0, int(self.width() * 0.97), int(self.height() * 0.99))

        match_time_text = ""
        if self.map_pattern_matching:
            spin_line = ['|', '/', '-', '\\'][int(time.time() * 4) % 4]
            match_time_text = f"正在识别中... {spin_line}"
        elif self.map_pattern_match_time > 0:
            elapsed = time.time() - self.map_pattern_match_time
            match_time_text = f"识别时间：{get_readable_timedelta(timedelta(seconds=elapsed))}前"
        else:
            match_time_text = ""

        if self.crystal_layout_idx is not None:
            crystal_layout_text = "大空洞水晶布局 "
            if self.crystal_layout_idx == 0:
                crystal_layout_text += "所有"
            else:
                crystal_layout_text += f"{self.crystal_layout_idx}"
            crystal_layout_text += f"/{len(self.crystal_layout_imgs) - 1}\n"
            match_time_text = crystal_layout_text + match_time_text

        self.match_time_label.setText(match_time_text)

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
            visible = visible and (self.is_game_foreground or self.is_menu_opened or self.is_setting_opened)
        if visible and not self.isVisible():
            self.show()
        elif not visible and self.isVisible():
            self.hide()

    def nextCrystalLayout(self):
        if self.visible and self.crystal_layout_idx is not None:
            self.crystal_layout_idx += 1
            if self.crystal_layout_idx >= len(self.crystal_layout_imgs):
                self.crystal_layout_idx = 0
            self.update_crystal_layout()

    def lastCrystalLayout(self):
        if self.visible and self.crystal_layout_idx is not None:
            self.crystal_layout_idx -= 1
            if self.crystal_layout_idx < 0:
                self.crystal_layout_idx = len(self.crystal_layout_imgs) - 1
            self.update_crystal_layout()

        