"""Verify augmentation evaluation coordinates and refusal accounting independently of HP accuracy."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from PIL import Image

from tests.support import hp_video
from tests.support.hp_augmentations import Augmentation, augmentations


@pytest.mark.parametrize("scale", [1, 0.75])
def test_evaluation_scales_labels_and_tolerance_and_counts_start_and_tail_rejections(monkeypatch, scale):
    # The fractional resize rounds 1250 * .75 to 938, so using the nominal .75
    # scale (or rounding the GT) would distort the comparison coordinate system.
    rgb = np.zeros((10, 1250, 3), dtype=np.uint8)
    rgb[5, :, 0] = 255
    transformed = Augmentation("scale", scale).apply(Image.fromarray(rgb))
    width_ratio = transformed.width / 1250
    observed = []
    lengths = iter(
        [None, round(396 * width_ratio), None, None, round(396 * width_ratio) + 3, None, None, None]
    )

    class Capture:
        count = 0

        def isOpened(self):
            return True

        def get(self, prop):
            assert prop == cv2.CAP_PROP_FPS
            return 2

        def read(self):
            self.count += 1
            return (True, rgb[:, :, ::-1].copy()) if self.count <= 8 else (False, None)

        def release(self):
            pass

    class Detector:
        def detect(self, image, settings):
            observed.append(image.copy())
            return next(lengths)

    monkeypatch.setattr(hp_video.cv2, "VideoCapture", lambda _: Capture())
    monkeypatch.setattr(hp_video, "HpDetector", Detector)
    label = {"id": "synthetic", "video": "unused", "fps": 2, "decoded_frame_count": 8, "gt_length_px": 396}
    report = hp_video.evaluate_video(label, augmentation=Augmentation("scale", scale))
    assert report["gt_length_px"] == 396 * width_ratio
    assert report["tolerance_px"] == 3 * width_ratio
    assert report["incorrect"] == (0 if scale == 1 else 1)
    assert report["rejected"] == 6
    assert report["first_accepted_seconds"] == 0.5
    assert report["longest_rejection_seconds"] == 1.5
    assert report["evaluated_frames"] == report["decoded_frames"] == 8
    assert all(np.array_equal(image, np.asarray(transformed)) for image in observed)


def test_augmentation_catalog_is_complete_and_names_are_unique():
    variants = augmentations()
    assert len(variants) == len({variant.name for variant in variants}) == 32
    assert {variant.kind for variant in variants} == {
        "brightness",
        "saturation",
        "contrast",
        "sharpness",
        "blur",
        "gamma",
        "scale",
        "bright_combination",
        "dark_combination",
    }


@pytest.mark.parametrize(
    "interval,segments,expected",
    [
        (0, None, [0, 2, 4, 6]),
        (1, None, [0, 4]),
        (0, [(0, 1.5), (1.5, 4)], [0, 2, 3, 5, 7]),
    ],
)
def test_subsampling_preserves_timestamps_and_first_frame_after_capacity_changes(
    monkeypatch, interval, segments, expected
):
    observed = []

    class Detector:
        def detect(self, image, settings):
            observed.append(int(image[0, 0, 0]))
            return None if len(observed) == 1 else 100

    monkeypatch.setattr(hp_video, "HpDetector", Detector)
    monkeypatch.setattr(
        hp_video,
        "video_frames",
        lambda *args, **kwargs: (np.full((10, 120, 3), i, np.uint8) for i in range(8)),
    )
    label = {"id": "synthetic", "video": "unused", "fps": 2, "decoded_frame_count": 8, "gt_length_px": 100}
    if segments:
        label["gt_segments"] = [
            {"source_start_seconds": start, "source_end_seconds": end, "gt_length_px": 100}
            for start, end in segments
        ]
    report = hp_video.evaluate_video(label, interval_seconds=interval, sample_stride=2)
    assert observed == expected
    assert report["decoded_frames"] == 8
    assert report["detector_calls"] == report["evaluated_frames"] == len(expected)
    assert report["first_accepted_seconds"] == expected[1] / 2
    assert report["longest_rejection_seconds"] == expected[1] / 2
    assert report["incorrect"] == 0
