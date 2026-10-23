"""Lossless meter-region regression samples, augmentations and structural negatives."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from nightreign_overlay.plugins.debuff_timer.detector import DebuffDetector
from tests.support.debuff_images import combined_variants, variants

_ROOT = Path(__file__).parents[1] / "data/debuff"


@pytest.fixture(scope="module")
def detector():
    return DebuffDetector()


@pytest.mark.parametrize("path", sorted(_ROOT.glob("*.png")), ids=lambda path: path.name)
def test_real_meter_regions_and_augmentations(detector, path):
    rgb = cv2.cvtColor(
        cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB
    )
    expected = path.stem.split("_")[0] != "None"
    for index, variant in enumerate(variants(rgb)):
        result = detector.detect(variant)
        assert result.present == expected, (path.name, index, result)


@pytest.mark.parametrize("path", sorted(_ROOT.glob("*.png")), ids=lambda path: path.name)
def test_combined_lighting_and_sharpness(detector, path):
    rgb = cv2.cvtColor(
        cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB
    )
    expected = path.stem.split("_")[0] != "None"
    for parameters, image in combined_variants(rgb):
        result = detector.detect(image)
        assert result.present == expected, (path.name, parameters, result)


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
