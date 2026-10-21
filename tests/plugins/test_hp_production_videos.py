"""All four original-context videos through the public production detector."""

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from nightreign_overlay.core.images import read_cv2_image
from nightreign_overlay.plugins.hp_marker import material
from tests.support.hp_production_evaluation import (
    evaluate_production_smoke,
    heldout_block_label,
    production_labels,
)
from tests.support.hp_video import VIDEO_ROOT


def test_packaged_model_artifacts_match_training_provenance():
    root = Path(material.__file__).with_name("data")
    metadata = json.loads((root / "training.json").read_text(encoding="utf-8"))
    assert metadata["material_classes"] == ["usable", "gray", "background"]
    assert not metadata["holdout_alternating_five_second_blocks"]
    assert {item["id"] for item in metadata["provenance"]} == {label["id"] for label in production_labels()}
    for name, expected in metadata["artifacts"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected


def test_heldout_scoring_blocks_do_not_overlap_training_or_mutate_labels():
    metadata = json.loads((VIDEO_ROOT / "heldout_training.json").read_text(encoding="utf-8"))
    assert metadata["holdout_alternating_five_second_blocks"]
    for label in production_labels():
        before = json.dumps(label, sort_keys=True)
        heldout = heldout_block_label(label)
        assert json.dumps(label, sort_keys=True) == before
        assert heldout["gt_segments"]
        for part in heldout["gt_segments"]:
            assert int(part["source_start_seconds"] // 5) % 2 == 1
            assert part["source_end_seconds"] <= (int(part["source_start_seconds"] // 5) + 1) * 5
        provenance = next(item for item in metadata["provenance"] if item["id"] == label["id"])
        assert provenance["source_sha256"] == label["source_sha256"]
        for field in ("material_training_frame_indices", "cap_training_frame_indices"):
            assert provenance[field]
            assert all(int(frame / label["fps"] // 5) % 2 == 0 for frame in provenance[field])


@pytest.mark.parametrize("label", production_labels()[:2], ids=lambda label: label["id"])
def test_production_capacity_fixtures_preserve_all_pixels_and_reference_frames(label):
    path = VIDEO_ROOT / label["video"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == label["video_sha256"]
    references = {item["frame_index"]: item["image"] for item in label["reference_frames"]}
    capture = cv2.VideoCapture(str(path))
    assert capture.isOpened()
    digest = hashlib.sha256()
    count = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            digest.update(frame.tobytes())
            if count in references:
                assert np.array_equal(frame, read_cv2_image(VIDEO_ROOT / references[count]))
            count += 1
    finally:
        capture.release()
    assert count == label["decoded_frame_count"]
    assert digest.hexdigest() == label["decoded_pixel_sha256"]


@pytest.mark.parametrize("label", production_labels(), ids=lambda label: label["id"])
def test_production_video_short_windows(label):
    reports = evaluate_production_smoke(label)
    assert reports
    for report in reports:
        assert report["evaluated"] == 12, report
        assert report["incorrect"] == 0, report
        assert report["rejection_ratio"] <= 0.5, report
        assert report["first_accepted_after_seconds"] is not None, report
        assert report["first_accepted_after_seconds"] < 2.5, report
