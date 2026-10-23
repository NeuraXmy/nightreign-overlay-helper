"""Color, sharpness and geometry variants for Undertaker icon regression."""

from itertools import product

import cv2
import numpy as np


def legacy_variants(rgb):
    """Preserve the original 55 transformations, including shifted icon crops."""
    yield "original", rgb
    yield "blur", cv2.GaussianBlur(rgb, (7, 7), 2)
    for saturation, contrast, brightness in product((0.5, 0.75, 1, 1.25, 1.5), (0.6, 1, 1.4), (0.6, 1, 1.4)):
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = np.clip(hsv[..., 1].astype(float) * saturation, 0, 255)
        colored = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(float)
        yield (
            (saturation, contrast, brightness),
            np.clip(((colored - 127.5) * contrast + 127.5) * brightness, 0, 255).astype(np.uint8),
        )
    for brightness in (0.6, 0.8, 1.2, 1.4):
        yield (
            ("brightness", brightness),
            np.clip(rgb.astype(np.float32) * brightness, 0, 255).astype(np.uint8),
        )
    yield "scale", cv2.resize(rgb, (24, 24), interpolation=cv2.INTER_AREA)
    yield "sharpen", cv2.addWeighted(rgb, 1.8, cv2.GaussianBlur(rgb, (5, 5), 1), -0.8, 0)
    for offset in (-5, 5):
        transform = np.float32([[1, 0, offset], [0, 1, offset]])
        yield ("offset", offset), cv2.warpAffine(rgb, transform, (rgb.shape[1], rgb.shape[0]))


def combined_variants(rgb):
    """All 135 lighting and sharpness combinations, including stronger blur."""
    for saturation, contrast, brightness, sharpness in product(
        (0.5, 0.75, 1, 1.25, 1.5), (0.6, 1, 1.4), (0.6, 1, 1.4), ("original", "blur", "sharpen")
    ):
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = np.clip(hsv[..., 1].astype(float) * saturation, 0, 255)
        colored = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(float)
        image = np.clip(((colored - 127.5) * contrast + 127.5) * brightness, 0, 255).astype(np.uint8)
        if sharpness == "blur":
            image = cv2.GaussianBlur(image, (7, 7), 2)
        elif sharpness == "sharpen":
            image = cv2.addWeighted(image, 1.8, cv2.GaussianBlur(image, (5, 5), 1), -0.8, 0)
        yield (saturation, contrast, brightness, sharpness), image
