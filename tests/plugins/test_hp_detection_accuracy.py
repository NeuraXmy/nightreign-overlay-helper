"""Real-capture regressions and refusals for the deployed HP boundary detectors."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageEnhance, ImageFilter

from nightreign_overlay.plugins.hp_marker.config import HpDetectionSettings
from nightreign_overlay.plugins.hp_marker.detector import HpDetector
from nightreign_overlay.plugins.hp_marker.structural import estimate_boundary
from tests.support.paths import PROJECT_ROOT

CAPTURES = PROJECT_ROOT / "tests/data/hp_detect"


def _image(name: str) -> Image.Image:
    with Image.open(CAPTURES / name) as image:
        return image.convert("RGB")


def _width(name: str) -> int:
    path = CAPTURES / "gt" / name
    if not path.exists():
        path = path.with_suffix(".png")
    with Image.open(path) as gt:
        return gt.width


@pytest.mark.parametrize("name", [f"{number}.jpg" for number in (1, 4, 5, 7, 8, 9, 10, 11, 12)])
def test_clear_boundaries_exclude_limit_loss_and_scene(name):
    detector = HpDetector()
    image = np.array(_image(name))
    results = [detector.detect(image, HpDetectionSettings()) for _ in range(12)]
    assert results[0] is None  # Streaming detection confirms evidence across frames.
    assert results[-1] is not None
    assert all(length is None or abs(length - _width(name)) <= 3 for length in results)


@pytest.mark.parametrize("name", ["2.jpg", "3.jpg", "6.jpg"])
def test_ambiguous_or_missing_outer_context_is_rejected(name):
    # In 6.jpg the supplied image ends exactly at the GT width, without right context.
    detector = HpDetector()
    for _ in range(12):
        assert detector.detect(np.array(_image(name)), HpDetectionSettings()) is None


@pytest.mark.parametrize("name", ["4.jpg", "5.jpg", "7.jpg", "8.jpg", "9.jpg", "10.jpg", "11.jpg", "12.jpg"])
@pytest.mark.parametrize("kind,factor", [("brightness", 0.4), ("contrast", 0.25), ("saturation", 0.0)])
def test_photometric_changes_may_refuse_but_must_not_move_clear_boundaries(name, kind, factor):
    enhancers = {
        "brightness": ImageEnhance.Brightness,
        "contrast": ImageEnhance.Contrast,
        "saturation": ImageEnhance.Color,
    }
    image = enhancers[kind](_image(name)).enhance(factor)
    result = estimate_boundary(np.array(image))
    assert result.length is None or abs(result.length - _width(name)) <= 3
    detector = HpDetector()
    for _ in range(6):
        length = detector.detect(np.array(image), HpDetectionSettings())
        assert length is None or abs(length - _width(name)) <= 3


@pytest.mark.parametrize("scale", [0.5, 0.75, 1.25, 1.5, 2.0])
def test_full_health_length_scales_in_source_pixels(scale):
    source = _image("5.jpg")
    scaled = source.resize(
        (round(source.width * scale), round(source.height * scale)), Image.Resampling.LANCZOS
    )
    result = estimate_boundary(np.array(scaled))
    assert result.length is not None
    assert abs(result.length - _width("5.jpg") * scaled.width / source.width) <= 3 * scale


@pytest.mark.parametrize("value", [0, 64, 128, 255])
def test_uniform_images_have_no_bar(value):
    assert estimate_boundary(np.full((12, 800, 3), value, np.uint8)).length is None


def test_random_texture_and_unframed_stripes_are_rejected():
    rng = np.random.default_rng(20261015)
    for _ in range(20):
        noise = rng.integers(0, 220, (12, 800, 3), dtype=np.uint8)
        assert estimate_boundary(noise).length is None
    stripe = np.tile(np.linspace(30, 230, 800, dtype=np.uint8), (12, 1))
    assert estimate_boundary(np.repeat(stripe[:, :, None], 3, axis=2)).length is None


@pytest.mark.parametrize(
    "shape,dtype", [((12, 800), np.uint8), ((12, 800, 4), np.uint8), ((12, 800, 3), float)]
)
def test_invalid_rgb_input_is_rejected(shape, dtype):
    assert estimate_boundary(np.zeros(shape, dtype=dtype)).reason == "invalid_rgb_input"


def test_estimator_does_not_mutate_or_retain_input():
    image = np.array(_image("5.jpg"))
    before = image.copy()
    valid = estimate_boundary(image)
    assert np.array_equal(image, before)
    assert estimate_boundary(np.zeros_like(image)).length is None
    assert estimate_boundary(image) == valid


@pytest.mark.parametrize("number", range(1, 13))
def test_only_the_center_scanline_affects_detection(number):
    image = np.array(_image(f"{number}.jpg"))
    expected = estimate_boundary(image)
    rng = np.random.default_rng(20261015)
    modified = rng.integers(0, 256, image.shape, dtype=np.uint8)
    modified[image.shape[0] // 2] = image[image.shape[0] // 2]
    assert estimate_boundary(modified) == expected
    # Extra rows may be scene or UI; horizontal smoothing must never read them.
    padded = np.pad(image, ((9, 9), (0, 0), (0, 0)), constant_values=255)
    assert estimate_boundary(padded) == expected
    assert estimate_boundary(image[image.shape[0] // 2 : image.shape[0] // 2 + 1]) == expected


@pytest.mark.parametrize("number", [10, 11, 12])
@pytest.mark.parametrize("scale", [0.5, 0.75, 1.25, 1.5, 2.0])
def test_new_capture_scaling_may_refuse_but_must_not_move_the_boundary(number, scale):
    name = f"{number}.jpg"
    source = _image(name)
    scaled = source.resize(
        (round(source.width * scale), round(source.height * scale)), Image.Resampling.LANCZOS
    )
    ratio = scaled.width / source.width
    length = estimate_boundary(np.array(scaled)).length
    assert length is None or abs(length - _width(name) * ratio) <= 3 * ratio


@pytest.mark.parametrize("number", [10, 11, 12])
def test_extra_right_context_does_not_change_new_capture_boundary(number):
    image = np.array(_image(f"{number}.jpg"))
    expected = estimate_boundary(image)
    extended = np.pad(image, ((0, 0), (0, 1000), (0, 0)), mode="edge")
    assert estimate_boundary(extended) == expected


@pytest.mark.parametrize("number", range(1, 13))
@pytest.mark.parametrize(
    "kind,factor",
    [
        ("brightness", 1.8),
        ("contrast", 2.5),
        ("saturation", 0.2),
        ("sharpness", 6.0),
        ("blur", 2.0),
        ("blur", 4.0),
        ("gamma", 2.2),
    ],
)
def test_strong_augmentations_do_not_turn_internal_divisions_into_endpoints(number, kind, factor):
    name = f"{number}.jpg"
    source = _image(name)
    if kind == "blur":
        image = source.filter(ImageFilter.GaussianBlur(factor))
    elif kind == "gamma":
        image = source.point([round(255 * (value / 255) ** factor) for value in range(256)] * 3)
    else:
        enhancer = {
            "brightness": ImageEnhance.Brightness,
            "contrast": ImageEnhance.Contrast,
            "saturation": ImageEnhance.Color,
            "sharpness": ImageEnhance.Sharpness,
        }[kind]
        image = enhancer(source).enhance(factor)
    length = estimate_boundary(np.array(image)).length
    assert length is None or abs(length - _width(name)) <= 3
    detector = HpDetector()
    for _ in range(6):
        length = detector.detect(np.array(image), HpDetectionSettings())
        assert length is None or abs(length - _width(name)) <= 3
