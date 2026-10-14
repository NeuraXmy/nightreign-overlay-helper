"""Independent map overlay with the legacy image layers, crystal layouts and 50 ms opacity easing."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from functools import partial

import yaml
from PIL import Image
from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPixmap
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QSizePolicy, QVBoxLayout

from nightreign_overlay.core.log import get_logger
from nightreign_overlay.plugins.map_detect.image_utils import draw_text
from nightreign_overlay.plugins.map_detect.localization import rendering_translator
from nightreign_overlay.plugins.map_detect.resources import get_data_path
from nightreign_overlay.ui.overlay import OverlayConfig, OverlayManager, OverlayWindow

log = get_logger(__name__)


def load_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_readable_timedelta(t: timedelta, tr: Callable[..., str] | None = None) -> str:
    if tr is None:
        localized = rendering_translator()
        tr = partial(localized.tr, "map_detect")
    seconds = int(t.total_seconds())
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return tr("overlay.duration.hours", hours=hours, minutes=minutes, seconds=seconds)
    if minutes > 0:
        return tr("overlay.duration.minutes", minutes=minutes, seconds=seconds)
    return tr("overlay.duration.seconds", seconds=seconds)


@dataclass
class MapOverlayState:
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


class MapInfoOverlay(OverlayWindow):
    def __init__(self, manager: OverlayManager, config: OverlayConfig, tr: Callable[..., str]) -> None:
        self._real_opacity = 0.0
        self.visible = True
        self._suppressed = False
        self._tr = tr
        super().__init__(manager, config, tr("plugin.name"), QSize(10, 10))
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

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
        self.crystal_layout_image_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.crystal_layout_image_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crystal_layout_image_box.setScaledContents(True)

        # 右下角标签VBOX
        self.vbox = QVBoxLayout(self)
        self.vbox.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        def add_shadow(label: QLabel) -> None:
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

        self.update_ui_state(
            MapOverlayState(
                w=10,
                h=10,
                opacity=0.0,
                visible=True,
            )
        )

    def set_overlay_images(self, imgs: list[Image.Image] | None) -> None:
        self.overlay_images = imgs
        self.map_pattern_idx = 0
        self.update_overlay_images()

    def update_overlay_images(self) -> None:
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

    def next_overlay_image(self) -> None:
        if self.overlay_images is not None:
            self.map_pattern_idx += 1
            if self.map_pattern_idx >= len(self.overlay_images):
                self.map_pattern_idx = 0
            self.update_overlay_images()

    def last_overlay_image(self) -> None:
        if self.overlay_images is not None:
            self.map_pattern_idx -= 1
            if self.map_pattern_idx < 0:
                self.map_pattern_idx = len(self.overlay_images) - 1
            self.update_overlay_images()

    def init_crystal_layout_imgs(self) -> None:
        def load_pil_img(path: str, size: tuple[int, int], alpha: float) -> Image.Image:
            if not os.path.isfile(path):
                log.error(f"Failed to open image file: {path}")
            icon = Image.open(path).convert("RGBA")
            icon = icon.resize(size, Image.Resampling.BICUBIC)
            if alpha < 1.0:
                r, g, b, a = icon.split()
                a = a.point(lambda p: int(p * alpha))
                icon = Image.merge("RGBA", (r, g, b, a))
            return icon

        map_size = (750, 750)
        icon_size = (map_size[0] // 25, map_size[1] // 25)
        icon_alpha = 0.8
        spec_pattern_icon_size = (map_size[0] // 20, map_size[1] // 20)
        spec_pattern_icon_alpha = 0.8

        self.crystal_layout_imgs = []

        data = load_yaml(get_data_path("crystal.yaml"))

        crystals, underground_crystals = data["crystals"], data["underground_crystals"]
        for pattern in data["patterns"]:
            is_main = set(pattern["initial"]) == set(crystals.keys()) | set(underground_crystals.keys())

            size = spec_pattern_icon_size if not is_main else icon_size
            alpha = spec_pattern_icon_alpha if not is_main else icon_alpha
            icon = load_pil_img(get_data_path("icons/crystal/crystal.png"), size, alpha)
            icon_later = load_pil_img(get_data_path("icons/crystal/later_crystal.png"), size, alpha)
            icon_underground = load_pil_img(
                get_data_path("icons/crystal/underground_crystal.png"), size, alpha
            )

            img = Image.new("RGBA", map_size, (0, 0, 0, 0))

            def draw_crystal(idx: int, later: bool) -> None:
                if later:
                    icon_img = icon_later  # noqa: B023 -- immediate loop-local drawing helper
                elif idx in underground_crystals:
                    icon_img = icon_underground  # noqa: B023 -- immediate loop-local drawing helper
                else:
                    icon_img = icon  # noqa: B023 -- immediate loop-local drawing helper
                x_ratio, y_ratio = underground_crystals[idx] if idx in underground_crystals else crystals[idx]
                x = int(x_ratio * map_size[0]) - icon_img.width // 2
                y = int(y_ratio * map_size[1]) - icon_img.height // 2
                img.alpha_composite(icon_img, (x, y))  # noqa: B023 -- invoked before next iteration

            for idx in pattern["initial"]:
                draw_crystal(idx, later=False)
            for idx in pattern["later"]:
                draw_crystal(idx, later=True)

            # 图片正下方中间绘制图例
            sx = map_size[0] * 0.2
            sy = map_size[1] * 0.87
            if not is_main:
                img.alpha_composite(icon, (int(sx), int(sy)))
                draw_text(
                    img,
                    (sx + icon_size[0] + 5, sy),
                    self._tr("overlay.legend.crystal"),
                    20,
                    color=(255, 255, 255, 220),
                    outline_width=2,
                    align="lt",
                )
                img.alpha_composite(icon_underground, (int(sx), int(sy + icon_size[1])))
                draw_text(
                    img,
                    (sx + icon_size[0] + 5, sy + icon_size[1]),
                    self._tr("overlay.legend.underground"),
                    20,
                    color=(255, 255, 255, 220),
                    outline_width=2,
                    align="lt",
                )
                img.alpha_composite(icon_later, (int(sx), int(sy + 2 * (icon_size[1]))))
                draw_text(
                    img,
                    (sx + icon_size[0] + 5, sy + 2 * (icon_size[1])),
                    self._tr("overlay.legend.extra"),
                    20,
                    color=(255, 255, 255, 220),
                    outline_width=2,
                    align="lt",
                )
            else:
                img.alpha_composite(icon, (int(sx), int(sy + icon_size[1])))
                draw_text(
                    img,
                    (sx + icon_size[0] + 5, sy + icon_size[1]),
                    self._tr("overlay.legend.crystal"),
                    20,
                    color=(255, 255, 255, 220),
                    outline_width=2,
                    align="lt",
                )
                img.alpha_composite(icon_underground, (int(sx), int(sy + 2 * (icon_size[1]))))
                draw_text(
                    img,
                    (sx + icon_size[0] + 5, sy + 2 * (icon_size[1])),
                    self._tr("overlay.legend.underground"),
                    20,
                    color=(255, 255, 255, 220),
                    outline_width=2,
                    align="lt",
                )

            self.crystal_layout_imgs.append(img)

    def update_crystal_layout(self) -> None:
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

    def next_crystal_layout(self) -> None:
        if self.crystal_layout_idx is not None:
            self.crystal_layout_idx += 1
            if self.crystal_layout_idx >= len(self.crystal_layout_imgs):
                self.crystal_layout_idx = 0
            self.update_crystal_layout()

    def last_crystal_layout(self) -> None:
        if self.crystal_layout_idx is not None:
            self.crystal_layout_idx -= 1
            if self.crystal_layout_idx < 0:
                self.crystal_layout_idx = len(self.crystal_layout_imgs) - 1
            self.update_crystal_layout()

    def update_ui_state(self, state: MapOverlayState) -> None:
        if state.x is not None:
            self.set_map_region(QRect(state.x, state.y, state.w, state.h))
        if state.opacity is not None:
            self.target_opacity = state.opacity
        if state.visible is not None:
            self.visible = state.visible
        if state.overlay_images is not None:
            self.set_overlay_images(state.overlay_images)
        if state.clear_image:
            self.set_overlay_images(None)
        if state.map_pattern_matching is not None:
            self.map_pattern_matching = state.map_pattern_matching
        if state.map_pattern_match_time is not None:
            self.map_pattern_match_time = state.map_pattern_match_time
        if state.display_crystal_layout is not None:
            self.crystal_layout_idx = 0 if state.display_crystal_layout else None
            self.update_crystal_layout()
        self.show_overlay()
        self.update()

    def _tick(self) -> None:
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
            map_pattern_text = self._tr(
                "overlay.result", index=self.map_pattern_idx + 1, total=len(self.overlay_images)
            )
        self.map_pattern_label.setText(map_pattern_text)
        self.map_pattern_label.setStyleSheet(f"color: white; font-size: {font_size}px;")

        # 更新水晶布局标签
        crystal_layout_text = ""
        if self.crystal_layout_idx is not None:
            crystal_layout_text = self._tr("overlay.crystal")
            if self.crystal_layout_idx == 0:
                crystal_layout_text += self._tr("overlay.all")
            else:
                crystal_layout_text += f"{self.crystal_layout_idx}"
            crystal_layout_text += f"/{len(self.crystal_layout_imgs) - 1}"
        self.crystal_layout_label.setText(crystal_layout_text)
        self.crystal_layout_label.setStyleSheet(f"color: white; font-size: {font_size}px;")

        # 更新识别时间标签
        match_time_text = ""
        if self.map_pattern_matching:
            spin_line = ["|", "/", "-", "\\"][int(time.time() * 4) % 4]
            match_time_text = self._tr("overlay.matching", spinner=spin_line)
        elif self.map_pattern_match_time > 0:
            elapsed = time.time() - self.map_pattern_match_time
            match_time_text = self._tr(
                "overlay.elapsed", elapsed=get_readable_timedelta(timedelta(seconds=elapsed), self._tr)
            )
        self.match_time_label.setText(match_time_text)
        self.match_time_label.setStyleSheet(f"color: white; font-size: {font_size}px;")

        # 更新透明度
        threshold = 0.01
        step = 0.6
        real_opacity = self._real_opacity
        dlt = self.target_opacity - real_opacity
        if abs(dlt) > threshold:
            real_opacity += dlt * step
            self._real_opacity = real_opacity
            self.setWindowOpacity(real_opacity)
        elif 0 < abs(dlt) <= threshold:
            real_opacity = self.target_opacity
            self._real_opacity = real_opacity
            self.setWindowOpacity(real_opacity)

        self.update_visibility()

    def set_suppressed(self, suppressed: bool) -> None:
        """Temporarily force-hide map information without losing its requested state."""
        self._suppressed = suppressed
        self.update_visibility()

    def should_be_visible(self) -> bool:
        return (
            not self._suppressed
            and self.visible
            and self._real_opacity > 0.01
            and super().should_be_visible()
        )

    def set_map_region(self, rect: QRect) -> None:
        # Match the selector's physical-pixel convention, including per-monitor DPI.
        screen = next(
            (
                s
                for s in QGuiApplication.screens()
                if 0 <= (rect.x() - s.geometry().x()) / s.devicePixelRatio() < s.geometry().width()
                and 0 <= (rect.y() - s.geometry().y()) / s.devicePixelRatio() < s.geometry().height()
            ),
            QGuiApplication.primaryScreen(),
        )
        ratio = screen.devicePixelRatio() if screen is not None else 1.0
        origin = screen.geometry().topLeft() if screen is not None else QPoint()
        size = QSize(max(1, int(rect.width() / ratio)), max(1, int(rect.height() / ratio)))
        self.set_base_size(size)
        self._move_to(
            QPoint(
                origin.x() + int((rect.x() - origin.x()) / ratio),
                origin.y() + int((rect.y() - origin.y()) / ratio),
            )
        )

    def dispose(self) -> None:
        self._timer.stop()
        super().dispose()
