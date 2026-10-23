"""Synthetic continuous fill using the real three-down icon, preserving separators.

These are synthetic progress frames, not a recording of the game's animation.
"""

import cv2
import numpy as np


def continuous_progress(rgb: np.ndarray):
    h, w = rgb.shape[:2]
    y, x = np.mgrid[:h, :w]
    nx, ny = (x - (w - 1) / 2) / (w / 2), (y - (h - 1) / 2) / (h / 2)
    radius = np.hypot(nx, ny)
    angle = (np.degrees(np.arctan2(ny, nx)) + 90) % 360
    separator = np.minimum.reduce([np.abs((angle - center + 180) % 360 - 180) for center in (0, 120, 240)])
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    # Only repaint bright purple pixels; preserve black outlines, separator
    # spokes, central disk and all scene pixels outside the annulus.
    mask = (
        (radius > 0.34)
        & (radius < 0.90)
        & (separator > 7)
        & (hsv[..., 0] > 110)
        & (hsv[..., 0] < 155)
        & (hsv[..., 1] > 65)
        & (hsv[..., 2] > 100)
    )
    empty = rgb.copy()
    empty[mask] = (40, 40, 40)
    angles = sorted(set(np.linspace(0, 360, 721)) | {0.01, 119.9, 120.1, 239.9, 240.1, 359.99})
    for degrees in angles:
        image = empty.copy()
        filled = mask & (angle < degrees)
        image[filled] = rgb[filled]
        yield degrees, image
