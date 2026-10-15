"""Production full-map acceptance and robustness budgets on checked-in captures."""

import numpy as np
import pytest
from PIL import Image, ImageEnhance, ImageFilter
from scripts.benchmark_full_map import EXCLUDED_CAPTURES, benchmark

from nightreign_overlay.plugins.map_detect.detector import MapDetector, MapDetectParam
from tests.support.paths import MAP_CAPTURE_DIR


@pytest.fixture(scope="module")
def full_map_report():
    return benchmark(MAP_CAPTURE_DIR)


@pytest.mark.parametrize(
    ("group", "count", "minimum_correct"),
    [("original", 12, 12), ("enhanced", 216, 216), ("transparent", 288, 198), ("cropped", 180, 171)],
)
def test_full_map_robustness_keeps_acceptance_and_rejection_budgets(
    full_map_report, group, count, minimum_correct
):
    """All positives pass; negatives must at least retain pre-optimization rejection rates."""
    result = full_map_report["by_group"][group]
    assert result["count"] == count
    assert result["correct"] >= minimum_correct, result
    assert set(full_map_report["excluded_captures"]) == EXCLUDED_CAPTURES
    assert not EXCLUDED_CAPTURES.intersection(row["capture"] for row in full_map_report["rows"])


def test_full_map_public_detection_agrees_with_matcher(full_map_report):
    detector = MapDetector()
    for row in full_map_report["rows"]:
        if row["group"] != "original":
            continue
        with Image.open(MAP_CAPTURE_DIR / row["capture"]) as source:
            image = np.array(source.convert("RGB"))
        result = detector.detect(
            MapDetectParam(
                img=image,
                map_region=(0, 0, image.shape[1], image.shape[0]),
                do_match_full_map=True,
            )
        )
        assert result.is_full_map == row["predicted"], row["capture"]


@pytest.mark.parametrize(
    "path",
    sorted(path for path in MAP_CAPTURE_DIR.glob("*.jpg") if path.name not in EXCLUDED_CAPTURES),
    ids=lambda path: path.name,
)
def test_full_map_accepts_additional_enhancement_factors(path):
    """Exercise factors absent from the benchmark to avoid checking only its exact grid."""
    detector = MapDetector()
    with Image.open(path) as source:
        image = source.convert("RGB")
    images = [
        (f"{enhancer.__name__}_{factor}", enhancer(image).enhance(factor))
        for enhancer, factors in (
            (ImageEnhance.Color, (0.0, 2.5)),
            (ImageEnhance.Brightness, (0.45, 1.25)),
            (ImageEnhance.Contrast, (0.45, 1.25)),
            (ImageEnhance.Sharpness, (2.5,)),
        )
        for factor in factors
    ]
    images.append(("blur_0.75", image.filter(ImageFilter.GaussianBlur(0.75))))
    combined = ImageEnhance.Color(image).enhance(0.5)
    combined = ImageEnhance.Contrast(combined).enhance(0.8)
    images.append(("combined", ImageEnhance.Brightness(combined).enhance(0.8)))
    for name, enhanced in images:
        error = detector._match_full_map(np.array(enhanced))
        assert error <= detector.config.full_map_error_threshold, (name, error)


@pytest.mark.parametrize("value", [0, 64, 128, 255])
def test_full_map_rejects_featureless_images(value):
    detector = MapDetector()
    image = np.full((200, 200, 3), value, dtype=np.uint8)
    assert detector._match_full_map(image) == float("inf")


@pytest.mark.parametrize("shape", [(0, 0, 3), (4, 4, 3), (100, 100), (100, 100, 4)])
def test_full_map_rejects_invalid_or_too_small_images(shape):
    assert MapDetector()._match_full_map(np.zeros(shape, dtype=np.uint8)) == float("inf")
