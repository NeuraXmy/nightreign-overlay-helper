"""Filename ground truth and deterministic teammate HUD enhancements."""

from itertools import product
from pathlib import Path

import cv2
import numpy as np

SAMPLES = Path(__file__).parents[1] / "data/entertainment"


def sample_paths(root=SAMPLES):
    return sorted(root.glob("go_down*/*.png")) + sorted(root.glob("teammate_video/*.jpg"))


def expected_states(path):
    stem = path.stem.split("(")[0]
    labels = stem.split("_")[-1].split("-") if "-" in stem else stem.split("_")
    return tuple("1" if label == "2" else label for label in labels)


def states(teammates):
    return tuple(
        "n" if not t.present else "0" if not t.down else "3" if t.stages == 3 else "1" for t in teammates
    )


def variants(rgb):
    yield "original", rgb
    for saturation, contrast, brightness, sharpness in product(
        (0.5, 0.75, 1, 1.25, 1.5), (0.6, 1, 1.4), (0.6, 1, 1.4), ("original", "blur", "sharpen")
    ):
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = np.clip(hsv[..., 1].astype(float) * saturation, 0, 255)
        image = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(float)
        image = np.clip(((image - 127.5) * contrast + 127.5) * brightness, 0, 255).astype(np.uint8)
        if sharpness == "blur":
            image = cv2.GaussianBlur(image, (7, 7), 2)
        elif sharpness == "sharpen":
            image = cv2.addWeighted(image, 1.8, cv2.GaussianBlur(image, (5, 5), 1), -0.8, 0)
        yield (saturation, contrast, brightness, sharpness), image
    yield "mild-blur", cv2.GaussianBlur(rgb, (5, 5), 1)
    yield "mild-sharpen", cv2.addWeighted(rgb, 1.5, cv2.GaussianBlur(rgb, (5, 5), 1), -0.5, 0)
    for scale in (0.8, 1.5, 3):
        yield ("resolution", scale), cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
