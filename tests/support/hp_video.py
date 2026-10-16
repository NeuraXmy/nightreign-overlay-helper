"""Decode every fixture frame and evaluate the public HP detector against independent labels."""

from __future__ import annotations

import json
from time import perf_counter

import cv2
import numpy as np
from PIL import Image

from nightreign_overlay.plugins.hp_marker.config import HpDetectionSettings
from nightreign_overlay.plugins.hp_marker.detector import HpDetector
from nightreign_overlay.plugins.hp_marker.structural import estimate_boundary
from tests.support.hp_augmentations import Augmentation
from tests.support.paths import PROJECT_ROOT

VIDEO_ROOT = PROJECT_ROOT / "tests/data/hp_detect/videos"


def annotations() -> dict:
    return json.loads((VIDEO_ROOT / "annotations.json").read_text(encoding="utf-8"))


def evaluate_video(
    label: dict,
    *,
    interval_seconds: float = 0,
    single_frame: bool = False,
    augmentation: Augmentation | None = None,
) -> dict:
    """GT is used only after prediction; a new detector is created for each run.

    Rejected observations cover time until the next accepted observation, including
    startup and the tail of the video. Sampling still decodes all original frames.
    """
    capture = cv2.VideoCapture(str(VIDEO_ROOT / label["video"]))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot decode fixture: {label['video']}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    if fps != label["fps"]:
        capture.release()
        raise AssertionError(f"Unexpected FPS: {fps}")
    detector, settings = HpDetector(), HpDetectionSettings()
    tolerance = annotations()["tolerance_px"]
    frame_index = accepted = rejected = 0
    next_sample = 0.0
    rejection_start = first_accepted = None
    longest_rejection = max_error = 0.0
    mistakes: list[dict] = []
    predictions: list[int] = []
    costs: list[float] = []
    scale = 1.0
    try:
        while True:
            ok, bgr = capture.read()
            if not ok:
                break
            timestamp = frame_index / fps
            frame_index += 1
            if timestamp + 1e-9 < next_sample:
                continue
            next_sample += interval_seconds
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            if augmentation is not None:
                transformed = augmentation.apply(Image.fromarray(rgb))
                scale = transformed.width / rgb.shape[1]
                rgb = np.asarray(transformed)
            start = perf_counter()
            length = estimate_boundary(rgb).length if single_frame else detector.detect(rgb, settings)
            costs.append((perf_counter() - start) * 1000)
            if length is None:
                rejected += 1
                if rejection_start is None:
                    rejection_start = timestamp
                continue
            accepted += 1
            predictions.append(length)
            if first_accepted is None:
                first_accepted = timestamp
            if rejection_start is not None:
                longest_rejection = max(longest_rejection, timestamp - rejection_start)
                rejection_start = None
            error = abs(length - label["gt_length_px"] * scale)
            max_error = max(max_error, error)
            if error > tolerance * scale:
                mistakes.append({"frame": frame_index - 1, "seconds": timestamp, "length": length})
    finally:
        capture.release()
    duration = frame_index / fps
    if rejection_start is not None:
        longest_rejection = max(longest_rejection, duration - rejection_start)
    if frame_index != label["decoded_frame_count"]:
        raise AssertionError(f"Decoded {frame_index} frames; expected {label['decoded_frame_count']}")
    if not costs:
        raise AssertionError("No frames were evaluated")
    return {
        "id": label["id"],
        "algorithm": "single_frame_baseline" if single_frame else "structural",
        "augmentation": augmentation.name if augmentation else "original",
        "interval_seconds": interval_seconds,
        "decoded_frames": frame_index,
        "evaluated_frames": len(costs),
        "gt_length_px": label["gt_length_px"] * scale,
        "tolerance_px": tolerance * scale,
        "width_scale": scale,
        "prediction_range_px": [min(predictions), max(predictions)] if predictions else None,
        "accepted": accepted,
        "rejected": rejected,
        "rejection_ratio": rejected / len(costs),
        "incorrect": len(mistakes),
        "mistake_examples": mistakes[:10],
        "max_error_px": max_error,
        "first_accepted_seconds": first_accepted,
        "longest_rejection_seconds": longest_rejection,
        "detector_ms": {
            "mean": float(np.mean(costs)),
            "p95": float(np.percentile(costs, 95)),
            "max": max(costs),
        },
    }
