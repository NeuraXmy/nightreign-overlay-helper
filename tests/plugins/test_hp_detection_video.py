"""Whole-video accuracy, refusal limits and structural detector history regressions."""

from __future__ import annotations

import hashlib

import cv2
import numpy as np
import pytest
from PIL import Image

from nightreign_overlay.plugins.hp_marker.config import HpDetectionSettings
from nightreign_overlay.plugins.hp_marker.detector import HpDetector
from tests.support.hp_video import VIDEO_ROOT, annotations, evaluate_video

MANIFEST = annotations()


def _reference(video: int, frame: int) -> np.ndarray:
    with Image.open(VIDEO_ROOT / f"constant_length_{video}_frame_{frame}.png") as image:
        return np.array(image.convert("RGB"))


@pytest.mark.parametrize("label", MANIFEST["annotations"], ids=lambda label: label["id"])
def test_video_fixtures_match_saved_labels_and_references(label):
    assert hashlib.sha256((VIDEO_ROOT / label["video"]).read_bytes()).hexdigest() == label["video_sha256"]
    with Image.open(VIDEO_ROOT / label["gt_image"]) as gt:
        assert gt.size == (label["gt_length_px"], MANIFEST["crop_xywh"][3])
        reference = label["reference_frames"][0]["image"]
        with Image.open(VIDEO_ROOT / reference) as frame:
            assert np.array_equal(np.asarray(gt), np.asarray(frame)[:, : gt.width])
    capture = cv2.VideoCapture(str(VIDEO_ROOT / label["video"]))
    try:
        for reference in label["reference_frames"]:
            capture.set(cv2.CAP_PROP_POS_FRAMES, reference["frame_index"])
            ok, bgr = capture.read()
            assert ok
            with Image.open(VIDEO_ROOT / reference["image"]) as image:
                assert np.array_equal(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), np.asarray(image))
    finally:
        capture.release()


@pytest.mark.parametrize("interval_seconds", [0, 0.05, 0.25])
@pytest.mark.parametrize("label", MANIFEST["annotations"], ids=lambda label: label["id"])
def test_every_video_output_is_correct_with_bounded_rejections(label, interval_seconds):
    report = evaluate_video(label, interval_seconds=interval_seconds)
    assert report["incorrect"] == 0, report
    assert report["rejection_ratio"] <= MANIFEST["max_rejection_ratio"], report
    assert report["longest_rejection_seconds"] <= MANIFEST["max_rejection_seconds"], report


def test_tracking_rechecks_each_frame_and_recovers_after_real_length_changes():
    detector, settings = HpDetector(), HpDetectionSettings()
    image = _reference(2, 700)
    full = _reference(2, 0)
    for _ in range(12):
        detector.detect(full, settings)
        length = detector.detect(image, settings)
    assert length is not None and abs(length - 424) <= 3
    assert detector._structural._narrow
    # Extend the empty portion, keeping the left cap, current HP and source width.
    # This is a real endpoint change, not a change in GT supplied to the detector.
    added = np.tile(image[:, 390:400], (1, 8, 1))
    longer = np.concatenate((image[:, :400], added, image[:, 400:]), axis=1)[:, : image.shape[1]]
    assert detector.detect(longer, settings) is None
    outputs = [detector.detect(longer, settings) for _ in range(30)]
    assert any(value is not None for value in outputs)
    assert all(value is None or abs(value - 504) <= 3 for value in outputs)
    assert outputs[-1] is not None


def test_missing_hud_clears_history_and_never_returns_a_cached_length():
    detector, settings = HpDetector(), HpDetectionSettings()
    image = _reference(2, 700)
    for _ in range(10):
        detector.detect(image, settings)
    for _ in range(20):
        assert detector.detect(np.zeros_like(image), settings) is None
    assert detector.detect(image, settings) is None
    for _ in range(10):
        length = detector.detect(image, settings)
    assert length is not None and abs(length - 424) <= 3


def test_streaming_detection_reads_only_the_middle_row_and_does_not_mutate_input():
    image = _reference(2, 700)
    before = image.copy()
    rng = np.random.default_rng(20261016)
    modified = rng.integers(0, 256, image.shape, dtype=np.uint8)
    modified[image.shape[0] // 2] = image[image.shape[0] // 2]
    detectors = [HpDetector(), HpDetector(), HpDetector()]
    settings = HpDetectionSettings()
    row = image[image.shape[0] // 2 : image.shape[0] // 2 + 1]
    for _ in range(12):
        values = [
            detector.detect(source, settings)
            for detector, source in zip(detectors, (image, modified, row), strict=True)
        ]
        assert values[0] == values[1] == values[2]
    assert values[0] is not None
    assert np.array_equal(image, before)
