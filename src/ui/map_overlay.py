from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QRect
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
    overlay_images: list[Image.Image] | None = None
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

        # 悬浮地图信息
        self.map_pattern_idx: int | None = None
        self.overlay_images: list[Image.Image] | None = None
        self.map_pattern_match_time: float = 0.0
        self.map_pattern_matching: bool = False

        self.overlay_image_box = QLabel(self)
        self.overlay_image_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.overlay_image_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay_image_box.setScaledContents(True)

        # 悬浮水晶信息
        self.crystal_layout_idx: int | None = None
        self.init_crystal_layout_imgs()

        self.crystal_layout_image_box = QLabel(self)
        self.crystal_layout_image_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.crystal_layout_image_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crystal_layout_image_box.setScaledContents(True)

        # 右下角标签VBOX
        self.vbox = QVBoxLayout(self)
        self.vbox.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        def add_shadow(label: QLabel):
            shadow_effect = QGraphicsDropShadowEffect(label)
            shadow_effect.setBlurRadius(5)
            shadow_effect.setOffset(2, 2)
            shadow_effect.setColor(QColor(0, 0, 0, 160))
            label.setGraphicsEffect(shadow_effect)


        # 水晶序号标签
        self.crystal_layout_label = QLabel(self)
        self.crystal_layout_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        add_shadow(self.crystal_layout_label)
        self.vbox.addWidget(self.crystal_layout_label)

        # 地图序号标签
        self.map_pattern_label = QLabel(self)
        self.map_pattern_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        add_shadow(self.map_pattern_label)
        self.vbox.addWidget(self.map_pattern_label)

        # 检测时间标签
        self.match_time_label = QLabel(self)
        self.match_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        add_shadow(self.match_time_label)
        self.vbox.addWidget(self.match_time_label)


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


    def set_overlay_images(self, imgs: list[Image.Image] | None):
        self.overlay_images = imgs
        self.map_pattern_idx = 0
        self.update_overlay_images()
        
    def update_overlay_images(self):
        if not self.overlay_images:
            self.overlay_images = None
            self.overlay_image_box.clear()
            return
        img = self.overlay_images[self.map_pattern_idx]
        data = img.convert("RGBA").tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        pixmap.setDevicePixelRatio(self.devicePixelRatio())
        self.overlay_image_box.setPixmap(pixmap)

    def next_overlay_image(self):
        if self.visible and self.overlay_images is not None:
            self.map_pattern_idx += 1
            if self.map_pattern_idx >= len(self.overlay_images):
                self.map_pattern_idx = 0
            self.update_overlay_images()

    def last_overlay_image(self):
        if self.visible and self.overlay_images is not None:
            self.map_pattern_idx -= 1
            if self.map_pattern_idx < 0:
                self.map_pattern_idx = len(self.overlay_images) - 1
            self.update_overlay_images()


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
            sx = MAP_SIZE[0] * 0.2
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

    def update_crystal_layout(self):
        if self.crystal_layout_idx is None:
            self.crystal_layout_image_box.clear()
            return
        img = self.crystal_layout_imgs[self.crystal_layout_idx]
        img = img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        pixmap.setDevicePixelRatio(self.devicePixelRatio())
        self.crystal_layout_image_box.setPixmap(pixmap)

    def next_crystal_layout(self):
        if self.visible and self.crystal_layout_idx is not None:
            self.crystal_layout_idx += 1
            if self.crystal_layout_idx >= len(self.crystal_layout_imgs):
                self.crystal_layout_idx = 0
            self.update_crystal_layout()

    def last_crystal_layout(self):
        if self.visible and self.crystal_layout_idx is not None:
            self.crystal_layout_idx -= 1
            if self.crystal_layout_idx < 0:
                self.crystal_layout_idx = len(self.crystal_layout_imgs) - 1
            self.update_crystal_layout()


    def update_ui_state(self, state: MapOverlayUIState):
        if state.x is not None:
            region = mss_region_to_qt_region((state.x, state.y, state.w, state.h))
            self.setGeometry(*region)
        if state.opacity is not None:
            self.target_opacity = state.opacity
        if state.visible is not None:
            self.visible = state.visible
        if state.overlay_images is not None:
            self.set_overlay_images(state.overlay_images)
        if state.clear_image:
            self.set_overlay_images(None)
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
        w, h = self.width(), self.height()
        self.overlay_image_box.setGeometry(0, 0, w, h)
        self.crystal_layout_image_box.setGeometry(0, 0, w, h)

        font_size = max(8, 24 * h // 750)

        # 更新vbox
        margin = int(font_size * 0.5)
        self.vbox.setContentsMargins(margin, margin, margin, margin)
        self.vbox.setSpacing(margin // 2)

        # 更新地图序号标签
        map_pattern_text = ""
        if self.overlay_images is not None and self.map_pattern_idx is not None:
            map_pattern_text = f"识别结果: {self.map_pattern_idx + 1}/{len(self.overlay_images)}"
        self.map_pattern_label.setText(map_pattern_text)
        self.map_pattern_label.setStyleSheet(f"color: white; font-size: {font_size}px;")

        # 更新水晶布局标签
        crystal_layout_text = ""
        if self.crystal_layout_idx is not None:
            crystal_layout_text = "水晶布局: "
            if self.crystal_layout_idx == 0:
                crystal_layout_text += "所有"
            else:
                crystal_layout_text += f"{self.crystal_layout_idx}"
            crystal_layout_text += f"/{len(self.crystal_layout_imgs) - 1}"
        self.crystal_layout_label.setText(crystal_layout_text)
        self.crystal_layout_label.setStyleSheet(f"color: white; font-size: {font_size}px;")

        # 更新识别时间标签
        match_time_text = ""
        if self.map_pattern_matching:
            spin_line = ['|', '/', '-', '\\'][int(time.time() * 4) % 4]
            match_time_text = f"正在识别中... {spin_line}"
        elif self.map_pattern_match_time > 0:
            elapsed = time.time() - self.map_pattern_match_time
            match_time_text = f"识别时间：{get_readable_timedelta(timedelta(seconds=elapsed))}前"
        self.match_time_label.setText(match_time_text)
        self.match_time_label.setStyleSheet(f"color: white; font-size: {font_size}px;")

        # 更新透明度
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



