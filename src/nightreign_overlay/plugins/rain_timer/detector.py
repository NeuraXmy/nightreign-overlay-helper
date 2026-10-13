"""Port of the legacy HP bar colour (HLS) area-ratio detector for Deadly Nightrain."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage

from nightreign_overlay.plugins.capture.api import crop_rgb

Hls = Sequence[int]
#: Legacy built-in bounds ``(brightest, darkest)`` keyed by ``(in_rain, hdr)``;
#: a calibrated colour replaces both.
DEFAULT_HLS: dict[tuple[bool, bool], tuple[Hls, Hls]] = {
    (False, False): ((3, 80, 128), (5, 52, 166)),
    (True, False): ((163, 90, 130), (164, 62, 173)),
    (False, True): ((11, 91, 59), (9, 54, 88)),
    (True, True): ((156, 98, 48), (157, 64, 69)),
}


@dataclass(frozen=True)
class RainDetectResult:
    in_rain: bool | None
    not_in_rain_ratio: float
    in_rain_ratio: float
    seconds: float


def detect_rain(
    frame: QImage,
    region: QRect,
    not_in_rain: tuple[Hls, Hls],
    in_rain: tuple[Hls, Hls],
    tolerance: Hls,
    min_ratio: float,
    max_ratio: float,
) -> RainDetectResult | None:
    """Classify the HP bar by the share of pixels near the normal and the in-rain colours.

    The colour sample keeps the raw (non tone-mapped) pixels even with HDR processing, like the legacy app.
    """
    started = time.perf_counter()
    image = crop_rgb(frame, region)
    if image is None:
        return None
    hls = cv2.cvtColor(image, cv2.COLOR_RGB2HLS)
    total = hls.shape[0] * hls.shape[1]
    not_in_rain_ratio = _pixel_count(hls, *not_in_rain, tolerance) / total
    in_rain_ratio = _pixel_count(hls, *in_rain, tolerance) / total
    result: bool | None = None
    if in_rain_ratio >= max_ratio and not_in_rain_ratio <= min_ratio:
        result = True
    elif not_in_rain_ratio >= max_ratio and in_rain_ratio <= min_ratio:
        result = False
    return RainDetectResult(result, not_in_rain_ratio, in_rain_ratio, time.perf_counter() - started)


def dominant_hls(image: QImage) -> list[int] | None:
    """Most frequent HLS value of ``image`` (legacy ``get_to_detect_hp_hls`` histogram peak)."""
    rgb = crop_rgb(image)
    if rgb is None:
        return None
    pixels = cv2.cvtColor(rgb, cv2.COLOR_RGB2HLS).reshape(-1, 3)
    # ``np.unique`` sorts values like the legacy histogram's C-order scan, so ties resolve identically.
    values, counts = np.unique(pixels, axis=0, return_counts=True)
    return [int(value) for value in values[int(np.argmax(counts))]]


def hls_to_rgb(hls: Hls) -> tuple[int, int, int]:
    rgb = cv2.cvtColor(np.uint8([[list(hls)]]), cv2.COLOR_HLS2RGB)[0][0]
    return int(rgb[0]), int(rgb[1]), int(rgb[2])


def _pixel_count(hls: np.ndarray, first: Hls, second: Hls, tolerance: Hls) -> int:
    lower = np.minimum(first, second) - np.asarray(tolerance)
    upper = np.maximum(first, second) + np.asarray(tolerance)
    return int(np.count_nonzero(cv2.inRange(hls, lower, upper)))
