"""Deterministic status-meter image augmentations."""

from itertools import product

import cv2
import numpy as np


def variants(rgb):
    yield rgb
    for brightness in (0.6, 0.8, 1.2, 1.4):
        yield np.clip(rgb.astype(float) * brightness, 0, 255).astype(np.uint8)
    for contrast in (0.6, 1.4):
        yield np.clip((rgb.astype(float) - 127.5) * contrast + 127.5, 0, 255).astype(np.uint8)
    for saturation in (0.5, 1.5):
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = np.clip(hsv[..., 1].astype(float) * saturation, 0, 255)
        yield cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    yield cv2.GaussianBlur(rgb, (5, 5), 1)
    yield cv2.addWeighted(rgb, 1.5, cv2.GaussianBlur(rgb, (5, 5), 1), -0.5, 0)
    for dx, dy in ((-10, -5), (10, 5), (-5, 10), (5, -10)):
        yield cv2.warpAffine(
            rgb,
            np.float32([[1, 0, dx], [0, 1, dy]]),
            (rgb.shape[1], rgb.shape[0]),
            borderMode=cv2.BORDER_REFLECT,
        )
    for scale in (0.9, 1.1):
        matrix = cv2.getRotationMatrix2D((rgb.shape[1] / 2, rgb.shape[0] / 2), 0, scale)
        yield cv2.warpAffine(rgb, matrix, (rgb.shape[1], rgb.shape[0]), borderMode=cv2.BORDER_REFLECT)


def combined_variants(rgb, *, max_combined=4):
    for brightness, contrast, saturation, sharpness in product(
        (0.6, 1.0, 1.4), (0.6, 1.0, 1.4), (0.5, 1.0, 1.5), ("blur", "original", "sharpen")
    ):
        if sum((brightness != 1, contrast != 1, saturation != 1, sharpness != "original")) > max_combined:
            continue
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = np.clip(hsv[..., 1].astype(float) * saturation, 0, 255)
        image = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(float)
        image = np.clip(((image - 127.5) * contrast + 127.5) * brightness, 0, 255).astype(np.uint8)
        blurred = cv2.GaussianBlur(image, (5, 5), 1)
        if sharpness == "blur":
            image = blurred
        elif sharpness == "sharpen":
            image = cv2.addWeighted(image, 1.5, blurred, -0.5, 0)
        yield (brightness, contrast, saturation, sharpness), image
