"""Low-cost Undertaker active-art detection for tightly cropped RGB icons."""

from __future__ import annotations

import cv2
import numpy as np

PINK_RATIO_THRESHOLD = 0.80


def pink_ratio(rgb: np.ndarray) -> float:
    """Return pink coverage in a uint8 RGB icon (not a full-screen image).

    Downsample first to keep color conversion and thresholding at 1024 pixels,
    independent of capture resolution. Saturation/value floors reject gray and
    dark noise. The hue range covers the purple-to-magenta active glow, stopping
    at magenta (300 degrees) so red-tinted scenery and inactive icons do not
    count as pink merely because warm lighting pushes blue toward red.
    """
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Expected a uint8 RGB image with three channels")
    if rgb.shape[0] == 0 or rgb.shape[1] == 0:
        raise ValueError("Expected a nonempty icon")
    small = cv2.resize(rgb, (32, 32), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, (135, 12, 40), (150, 255, 255))
    return cv2.countNonZero(mask) / 1024


def is_active(rgb: np.ndarray) -> bool:
    """Identify the pink active icon; inactive blue icons return False."""
    return pink_ratio(rgb) >= PINK_RATIO_THRESHOLD
