from pathlib import Path

import cv2
import numpy as np
import pytest

from nightreign_overlay.core.images import read_cv2_image
from nightreign_overlay.plugins.art_timer.undertaker_detector import is_active

_SAMPLES = Path(__file__).parents[1] / "data" / "undertaker_art"


@pytest.mark.parametrize("name", [f"{index}.png" for index in range(7)])
def test_undertaker_active_icon_and_augmentations(name):
    rgb = cv2.cvtColor(read_cv2_image(_SAMPLES / name), cv2.COLOR_BGR2RGB)
    expected = name == "0.png"
    variants = [rgb, cv2.GaussianBlur(rgb, (7, 7), 2)]
    for saturation in (0.5, 0.75, 1, 1.25, 1.5):
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = np.clip(hsv[..., 1].astype(float) * saturation, 0, 255)
        colored = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(float)
        for contrast in (0.6, 1, 1.4):
            for brightness in (0.6, 1, 1.4):
                variants.append(
                    np.clip(((colored - 127.5) * contrast + 127.5) * brightness, 0, 255).astype(np.uint8)
                )
    for brightness in (0.6, 0.8, 1.2, 1.4):
        variants.append(np.clip(rgb.astype(np.float32) * brightness, 0, 255).astype(np.uint8))
    variants.append(cv2.resize(rgb, (24, 24), interpolation=cv2.INTER_AREA))
    variants.append(cv2.addWeighted(rgb, 1.8, cv2.GaussianBlur(rgb, (5, 5), 1), -0.8, 0))
    for offset in (-5, 5):
        transform = np.float32([[1, 0, offset], [0, 1, offset]])
        variants.append(cv2.warpAffine(rgb, transform, (rgb.shape[1], rgb.shape[0])))
    for index, image in enumerate(variants):
        assert is_active(image) == expected, (name, index)
