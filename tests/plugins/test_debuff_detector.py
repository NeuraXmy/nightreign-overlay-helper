"""Lossless meter-region regression samples, augmentations and structural negatives."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from nightreign_overlay.plugins.debuff_timer.detector import DebuffDetector

_ROOT = Path(__file__).parents[1] / "data/debuff"


@pytest.fixture(scope="module")
def detector():
    return DebuffDetector()


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


@pytest.mark.parametrize("path", sorted(_ROOT.glob("*.png")), ids=lambda path: path.name)
def test_real_meter_regions_and_augmentations(detector, path):
    rgb = cv2.cvtColor(
        cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB
    )
    expected = path.stem.split("_")[0] != "None"
    for index, variant in enumerate(variants(rgb)):
        result = detector.detect(variant)
        assert result.present == expected, (path.name, index, result)


def test_requires_icon_and_bar_together(detector):
    from nightreign_overlay.plugins.debuff_timer import detector as module

    for path in Path(module.__file__).with_name("icons").glob("*.png"):
        bgr = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        canvas = np.full((320, 450, 3), 64, np.uint8)
        canvas[80:128, 50:98] = cv2.cvtColor(cv2.resize(bgr, (48, 48)), cv2.COLOR_BGR2RGB)
        assert not detector.detect(canvas).present
    for value in (0, 240):
        canvas = np.full((320, 450, 3), 100, np.uint8)
        canvas[100:110, 110:350] = value
        assert not detector.detect(canvas).present
    assert not detector.detect(np.full((320, 450, 3), 64, np.uint8)).present


@pytest.mark.parametrize(
    "name,top,bottom",
    [
        ("0.png", 228, 288),
        ("04125.png", 35, 90),
        ("4125.png", 90, 142),
        ("4125.png", 140, 190),
        ("4125.png", 188, 237),
        ("4125.png", 238, 285),
        ("3.png", 225, 288),
        ("6.png", 228, 285),
    ],
)
def test_each_meter_row_is_detected_without_other_statuses(detector, name, top, bottom):
    bgr = cv2.imdecode(np.frombuffer((_ROOT / name).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    isolated = np.full_like(rgb, 80)
    isolated[top:bottom] = rgb[top:bottom]
    for index, image in enumerate(variants(isolated)):
        assert detector.detect(image).present, (name, top, index)
