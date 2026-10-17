"""Position-free vertical appearance features shared by training and inference."""

from __future__ import annotations

import cv2
import numpy as np


def material_features(image: np.ndarray) -> np.ndarray | None:
    """Normalize illumination against coloured fill and neighbouring scene rows."""
    rgb = cv2.resize(image, (image.shape[1], 24), interpolation=cv2.INTER_AREA).astype(np.float32)
    gray, color = rgb.mean(axis=2), np.ptp(rgb, axis=2)
    body_color = np.median(color[8:16], axis=0)
    threshold = max(12, 0.5 * float(np.quantile(body_color[4:32], 0.75)))
    columns = np.flatnonzero(body_color[4:50] > threshold) + 4
    if len(columns) < 4:
        return None
    reference = np.median(gray[:, columns], axis=1)
    reference_color = max(15, float(np.median(body_color[columns])))
    contrast = max(20, float(np.ptp(reference[8:16])))
    background = (gray[3:6].mean(axis=0) + gray[18:21].mean(axis=0)) / 2
    relative_fill = (gray - reference[8:16].mean()) / contrast
    relative_scene = (gray - background[None, :]) / np.maximum(20, background[None, :])
    chroma = color[8:16] / reference_color
    red_green = (rgb[8:16, :, 0] - rgb[8:16, :, 1]) / reference_color
    red_blue = (rgb[8:16, :, 0] - rgb[8:16, :, 2]) / reference_color
    return np.concatenate((relative_fill, relative_scene, chroma, red_green, red_blue), axis=0).T.copy()


def cap_features(features: np.ndarray, positions: np.ndarray) -> np.ndarray:
    """Inspect both sides of an endpoint without exposing its coordinate to the model."""
    return np.concatenate(
        [features[np.clip(positions + shift, 0, len(features) - 1)] for shift in (-6, -3, 0, 3, 6)],
        axis=1,
    )
