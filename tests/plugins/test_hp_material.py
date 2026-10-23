"""Capacity changes, empty/gray semantics and cold starts of the region path."""

import numpy as np
import pytest
from PIL import Image, ImageEnhance

from nightreign_overlay.plugins.hp_marker.config import HpDetectionSettings
from nightreign_overlay.plugins.hp_marker.detector import HpDetector
from nightreign_overlay.plugins.hp_marker.material import estimate_material_boundary
from tests.support.hp_assertions import assert_rejection_duration, assert_rejection_ratio
from tests.support.hp_production_evaluation import evaluate_production, production_labels
from tests.support.hp_video import VIDEO_ROOT, evaluate_video, hp_footage_annotations


def _frame(name: str) -> np.ndarray:
    with Image.open(VIDEO_ROOT / name) as image:
        return np.array(image.convert("RGB"))


@pytest.mark.parametrize("interval", [0, 0.05, 0.25])
@pytest.mark.parametrize("label", hp_footage_annotations()["annotations"], ids=lambda label: label["id"])
def test_capacity_change_videos_have_no_mistakes_and_low_refusal(label, interval):
    # Keep the sparse cadence: further thinning can starve temporal confirmation.
    report = evaluate_video(
        label, interval_seconds=interval, predecoded=True, sample_stride=2 if interval < 0.25 else 1
    )
    assert report["incorrect"] == 0, report
    assert_rejection_ratio(report["rejection_ratio"], context=f"{label['id']} interval={interval}s")
    assert_rejection_duration(
        report["longest_rejection_seconds"], context=f"{label['id']} interval={interval}s"
    )


def test_gray_bevel_is_excluded_but_flat_empty_hp_is_included():
    image = _frame("hp_footage_2_frame_600.png")
    before = image.copy()
    result = estimate_material_boundary(image)
    assert result is not None
    # Red ends around x=166, empty HP continues to the gray divider at x=205.
    # The original outer rectangle at x=398 contains the excluded gray suffix.
    assert result.usable is not None and abs(result.usable - 205) <= 3
    assert result.outer is not None and abs(result.outer - 398) <= 3
    assert np.array_equal(image, before)
    restored = estimate_material_boundary(_frame("hp_footage_2_frame_900.png"))
    assert restored is not None and restored.usable is not None
    assert abs(restored.usable - 398) <= 3


@pytest.mark.parametrize("endpoint", [95, 143, 267, 300])
def test_spliced_non_half_capacity_endpoints_are_measured_without_a_ratio_prior(endpoint):
    image = _frame("hp_footage_2_frame_600.png")
    delta = endpoint - 205
    if delta > 0:
        empty = np.repeat(image[:, 185:186], delta, axis=1)
        image = np.concatenate((image[:, :185], empty, image[:, 185:]), axis=1)
    else:
        image = np.concatenate((image[:, :60], image[:, 60 - delta :]), axis=1)
    detector = HpDetector()
    results = [detector.detect(image, HpDetectionSettings()) for _ in range(6)]
    assert results[:2] == [None, None]
    assert results[-1] is not None and abs(results[-1] - endpoint) <= 3
    assert all(value is None or abs(value - endpoint) <= 3 for value in results)


def test_both_change_directions_refuse_old_length_and_confirm_fresh_evidence():
    half = _frame("hp_footage_2_frame_600.png")
    full = _frame("hp_footage_2_frame_900.png")
    detector, settings = HpDetector(), HpDetectionSettings()
    for image, endpoint in [(half, 205), (full, 398), (half, 205)]:
        outputs = [detector.detect(image, settings) for _ in range(6)]
        assert outputs[:2] == [None, None]
        assert outputs[-1] is not None
        assert all(value is None or abs(value - endpoint) <= 3 for value in outputs)
    assert detector.detect(np.zeros_like(half), settings) is None
    assert [detector.detect(half, settings) for _ in range(2)] == [None, None]
    assert detector.detect(half, settings) is not None


def test_outer_rectangle_length_can_change_in_both_directions():
    full = np.pad(_frame("hp_footage_2_frame_900.png"), ((0, 0), (0, 180), (0, 0)), mode="edge")
    short = np.concatenate((full[:, :60], full[:, 208:], np.repeat(full[:, -1:], 148, axis=1)), axis=1)
    long = np.concatenate((full[:, :250], np.repeat(full[:, 250:251], 72, axis=1), full[:, 250:-72]), axis=1)
    assert short.shape == long.shape == full.shape
    detector, settings = HpDetector(), HpDetectionSettings()
    for image, endpoint in ((full, 398), (short, 250), (long, 470), (full, 398)):
        outputs = [detector.detect(image, settings) for _ in range(6)]
        assert outputs[:2] == [None, None]
        assert outputs[-1] is not None
        assert all(value is None or abs(value - endpoint) <= 3 for value in outputs)


def test_region_failure_does_not_reacquire_outer_gray_edge_through_scanline():
    image = _frame("hp_footage_2_frame_600.png")
    detector, settings = HpDetector(), HpDetectionSettings()
    for _ in range(6):
        detector.detect(image, settings)
    # Keep its center scanline, remove the vertical shading evidence.
    flat = np.repeat(image[image.shape[0] // 2 : image.shape[0] // 2 + 1], image.shape[0], axis=0)
    for _ in range(20):
        assert detector.detect(flat, settings) is None
    assert detector.detect(image, settings) is None


def test_overexposed_tight_crop_does_not_qualify_as_a_full_vertical_section():
    with Image.open(VIDEO_ROOT.parent / "8.jpg") as image:
        bright = np.asarray(ImageEnhance.Brightness(image.convert("RGB")).enhance(1.8))
    assert estimate_material_boundary(bright) is None


def test_vertical_common_brightness_change_preserves_empty_and_gray_materials():
    image = _frame("hp_footage_2_frame_600.png")
    # A smooth, neutral scene-light change cancels in the vertical differences.
    offset = np.rint(8 * np.sin(np.arange(image.shape[1]) / 35)).astype(np.int16)
    changed = np.clip(image.astype(np.int16) + offset[None, :, None], 0, 255).astype(np.uint8)
    result = estimate_material_boundary(changed)
    assert result is not None and result.usable is not None
    assert abs(result.usable - 205) <= 3


def test_unframed_color_and_texture_do_not_qualify_as_material_geometry():
    rng = np.random.default_rng(20261017)
    for _ in range(10):
        noise = rng.integers(0, 220, (24, 435, 3), dtype=np.uint8)
        assert estimate_material_boundary(noise) is None
    stripes = np.repeat(rng.integers(0, 220, (1, 435, 3), dtype=np.uint8), 24, axis=0)
    assert estimate_material_boundary(stripes) is None


def test_calibrated_middle_selects_hp_instead_of_more_saturated_other_bars():
    image = np.pad(_frame("hp_footage_2_frame_600.png"), ((0, 16), (0, 0), (0, 0)))
    image[26:34] = (10, 30, 220)
    result = estimate_material_boundary(image, scanline_y=14)
    assert result is not None and result.usable is not None
    assert (result.top, result.bottom) == (10, 18)
    assert abs(result.usable - 205) <= 3


@pytest.mark.parametrize("label", production_labels()[:2], ids=lambda label: label["id"])
def test_sampled_independent_starts_need_no_warmed_capacity(label):
    # Cold-start acceptance uses the pixels actually available to the main
    # program. Old narrow fixtures omit two required lower context rows.
    report = evaluate_production(label, intervals=(0.5,), predecoded=True, cold_start_step=2)
    assert report["cold_starts"]
    for window in report["cold_starts"]:
        assert window["incorrect"] == 0, window
        assert_rejection_ratio(
            window["rejection_ratio"], context=f"{label['id']} cold start at {window['start_seconds']}s"
        )
        assert window["first_accepted_after_seconds"] is not None, window
        assert window["first_accepted_after_seconds"] < 2, window
