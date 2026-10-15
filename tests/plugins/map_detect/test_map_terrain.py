"""Terrain recognition regressions using checked-in game captures."""

from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from nightreign_overlay.plugins.map_detect.config import MapDetectionSettings
from nightreign_overlay.plugins.map_detect.detector import MapDetector, MapDetectParam
from tests.support.paths import MAP_CAPTURE_DIR

_CAPTURES = sorted((MAP_CAPTURE_DIR).glob("*.jpg"))


@pytest.fixture(scope="module")
def detector():
    return MapDetector()


@pytest.mark.parametrize("path", _CAPTURES, ids=lambda path: path.name)
def test_ncc_capture_ground_truth(detector, path):
    """Check the public detection path, including the default acceptance threshold."""
    patterns = {pattern.id: pattern for pattern in detector.info.patterns}
    ids = [int(value) for value in path.stem.split("_")[0].split("-")]
    expected = {patterns[identifier].earth_shifting for identifier in ids}
    image = np.array(Image.open(path).convert("RGB"))
    result = detector.detect(
        MapDetectParam(
            map_region=(0, 0, image.shape[1], image.shape[0]), img=image, do_match_earth_shifting=True
        )
    )
    assert result.earth_shifting in expected, f"NCC={result.earth_shifting_score}"
    assert result.earth_shifting_score >= detector.config.earth_shifting_ncc_threshold


@pytest.mark.parametrize("algorithm", ["ncc", "template"])
def test_algorithm_thresholds_are_independent(detector, monkeypatch, algorithm):
    worker = MapDetector.__new__(MapDetector)
    worker.config = replace(
        MapDetectionSettings(),
        earth_shifting_algorithm=algorithm,
        earth_shifting_ncc_threshold=0.6,
        earth_shifting_error_threshold=50,
    )
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    param = MapDetectParam(map_region=(0, 0, 100, 100), img=image, do_match_earth_shifting=True)
    for score, accepted in ((0.7, True), (0.5, False)) if algorithm == "ncc" else ((40, True), (60, False)):
        monkeypatch.setattr(worker, f"_match_earth_shifting_{algorithm}", lambda _image, s=score: (4, s))
        assert worker.detect(param).earth_shifting == (4 if accepted else None)


def test_ncc_rejects_uniform_image_even_with_permissive_threshold(detector):
    worker = MapDetector.__new__(MapDetector)
    worker.config = replace(MapDetectionSettings(), earth_shifting_ncc_threshold=-1)
    image = np.full((100, 100, 3), 128, dtype=np.uint8)
    result = worker.detect(
        MapDetectParam(map_region=(0, 0, 100, 100), img=image, do_match_earth_shifting=True)
    )
    assert result.earth_shifting is None
