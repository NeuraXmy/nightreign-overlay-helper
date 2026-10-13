"""Port of the legacy DAY I/II/III white-mask template matcher."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage

from nightreign_overlay.plugins.capture.api import hdr_to_sdr

LANGUAGES = ("chs", "cht", "eng", "jp")
TEMPLATE_HEIGHT = 30
_MASK_LOWER_WHITE = np.array([0, 0, 200])
_MASK_UPPER_WHITE = np.array([179, 90, 255])
_SCALES = np.linspace(0.8, 1.2, 20)


@dataclass(frozen=True)
class DayDetectResult:
    day: int | None
    scores: tuple[float, float, float]
    seconds: float


@dataclass(frozen=True)
class _DayTemplates:
    masks: tuple[np.ndarray, np.ndarray, np.ndarray]
    # DAY II/III labels are wider than DAY I; their regions grow around the calibrated DAY I centre.
    width_ratios: tuple[float, float, float]


class DayDetector:
    def __init__(self, template_dir: Path) -> None:
        self._templates: dict[str, _DayTemplates] = {}
        for language in LANGUAGES:
            masks = []
            for day in range(1, 4):
                image = cv2.imread(str(template_dir / f"{language}_{day}.png"))
                if image is None:
                    break
                masks.append(
                    _white_mask(cv2.cvtColor(_resize_height(image, TEMPLATE_HEIGHT), cv2.COLOR_BGR2RGB))
                )
            if len(masks) == 3:
                width = masks[0].shape[1]
                self._templates[language] = _DayTemplates(
                    (masks[0], masks[1], masks[2]), tuple(mask.shape[1] / width for mask in masks)
                )

    def available(self, language: str) -> bool:
        return language in self._templates

    def detect(
        self, frame: QImage, region: QRect, language: str, threshold: float, *, hdr: bool = False
    ) -> DayDetectResult | None:
        templates = self._templates.get(language)
        if templates is None or not region.isValid():
            return None
        started = time.perf_counter()
        center_x = region.x() + region.width() // 2
        scores = []
        for mask, ratio in zip(templates.masks, templates.width_ratios, strict=True):
            width = int(region.width() * ratio)
            day_region = QRect(center_x - width // 2, region.y(), width, region.height())
            image = _crop_rgb(frame, day_region)
            if image is None:
                scores.append(float("inf"))
                continue
            if hdr:
                image = hdr_to_sdr(image)
            scores.append(_match_mask(_white_mask(_resize_height(image, TEMPLATE_HEIGHT)), mask))
        # Legacy order: the first day under the threshold wins.
        day = next((index for index, score in enumerate(scores, 1) if score < threshold), None)
        return DayDetectResult(day, (scores[0], scores[1], scores[2]), time.perf_counter() - started)


def _crop_rgb(frame: QImage, region: QRect) -> np.ndarray | None:
    region = region.intersected(frame.rect())
    if region.isEmpty():
        return None
    crop = frame.copy(region).convertToFormat(QImage.Format.Format_RGB888)
    ptr = crop.bits()
    ptr.setsize(crop.sizeInBytes())
    # Rows are padded to 4-byte boundaries, so slice each scanline before splitting channels.
    rows = np.frombuffer(ptr, np.uint8).reshape(crop.height(), crop.bytesPerLine())
    return rows[:, : crop.width() * 3].reshape(crop.height(), crop.width(), 3).copy()


def _resize_height(image: np.ndarray, height: int) -> np.ndarray:
    # The legacy detector normalizes the selected DAY label to the template height.
    # Matching an accidental full-screen selection at native resolution stalls the GUI thread.
    width = max(1, int(image.shape[1] * height / image.shape[0]))
    interpolation = cv2.INTER_AREA if image.shape[0] > height else cv2.INTER_LANCZOS4
    return cv2.resize(image, (width, height), interpolation=interpolation)


def _white_mask(image: np.ndarray) -> np.ndarray:
    return cv2.inRange(cv2.cvtColor(image, cv2.COLOR_RGB2HSV), _MASK_LOWER_WHITE, _MASK_UPPER_WHITE)


def _match_mask(image: np.ndarray, template: np.ndarray) -> float:
    score = float("inf")
    for scale in _SCALES:
        height, width = template.shape
        resized = cv2.resize(template, (int(width * scale), int(height * scale)))
        if resized.shape[0] > image.shape[0] or resized.shape[1] > image.shape[1]:
            continue
        score = min(score, cv2.minMaxLoc(cv2.matchTemplate(image, resized, cv2.TM_SQDIFF_NORMED))[0])
    return score
