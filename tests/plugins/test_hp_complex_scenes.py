"""Independent complex-scene labels and production capture regression."""

import hashlib

import cv2
import numpy as np
import pytest

from nightreign_overlay.core.images import read_cv2_image
from tests.support.hp_assertions import assert_rejection_duration, assert_rejection_ratio
from tests.support.hp_scene_evaluation import evaluate_scene, scene_geometry, scene_labels
from tests.support.hp_video import VIDEO_ROOT


@pytest.mark.parametrize("label", scene_labels(), ids=lambda label: label["id"])
def test_lossless_scene_fixture_and_reference_frames(label):
    path = VIDEO_ROOT / label["video"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == label["video_sha256"]
    assert label["gt_constant"] and not label["contains_limit_loss_gray"]
    assert label["gt_length_px"] == label["outer_cap_source_x"] - label["left_cap_source_x"]
    assert label["calibration_xywh"][0] == label["left_cap_source_x"]
    references = {reference["frame_index"]: reference["image"] for reference in label["reference_frames"]}
    capture = cv2.VideoCapture(str(path))
    assert capture.isOpened()
    assert capture.get(cv2.CAP_PROP_FPS) == label["fps"]
    pixels = hashlib.sha256()
    count = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            assert frame.shape == (label["fixture_crop_xywh"][3], label["fixture_crop_xywh"][2], 3)
            pixels.update(frame.tobytes())
            if count in references:
                reference = read_cv2_image(VIDEO_ROOT / references[count])
                assert reference is not None
                assert np.array_equal(frame, reference)
            count += 1
    finally:
        capture.release()
    assert count == label["decoded_frame_count"]
    assert pixels.hexdigest() == label["decoded_pixel_sha256"]


@pytest.mark.parametrize("label", scene_labels(), ids=lambda label: label["id"])
def test_production_view_preserves_left_anchor_and_screen_clipping_without_gt(label):
    crop, view, row = scene_geometry(label)
    assert crop.x() == label["left_cap_source_x"]
    assert crop.right() < label["source_size_px"][0]
    assert row == 15
    if label["id"] == "yellow_complex":
        # FFV1 stores an even width; its extra left context must not shift the input.
        assert view.getRect() == (1, 0, 711, 30)
        assert crop.right() == 719
    else:
        assert view.getRect() == (0, 0, 1250, 30)
    different_gt = dict(label, gt_length_px=123, outer_cap_source_x=132, gt_constant=False)
    assert scene_geometry(different_gt) == (crop, view, row)


@pytest.fixture(scope="module", params=scene_labels(), ids=lambda label: label["id"])
def scene_report(request):
    return evaluate_scene(request.param, intervals=(0.25,))


def test_complex_scene_capacity_accuracy(scene_report):
    report = scene_report["reports"][0]
    assert report["incorrect"] == 0, report
    assert_rejection_ratio(
        report["rejection_ratio"], context=f"{scene_report['id']} interval={report['interval_seconds']}s"
    )
    assert_rejection_duration(
        report["longest_rejection_seconds"],
        context=f"{scene_report['id']} interval={report['interval_seconds']}s",
    )
