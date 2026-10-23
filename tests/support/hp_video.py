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
from tests.support.video_frames import video_frames

VIDEO_ROOT = PROJECT_ROOT / "tests/data/hp_detect/videos"


def annotations() -> dict:
    return json.loads((VIDEO_ROOT / "annotations.json").read_text(encoding="utf-8"))


def hp_footage_annotations() -> dict:
    return json.loads((VIDEO_ROOT / "hp_footage_annotations.json").read_text(encoding="utf-8"))


def evaluate_video(
    label: dict,
    *,
    interval_seconds: float = 0,
    single_frame: bool = False,
    augmentation: Augmentation | None = None,
    predecoded: bool = False,
    sample_stride: int = 1,
) -> dict:
    """GT is used only after prediction; a new detector is created for each run.

    Rejected observations cover time until the next accepted observation, including
    startup and the tail of the video. Sampling traverses all original frames;
    predecoded=True reuses lossless saved frames across sampling rates and test runs.
    sample_stride subsamples scheduled observations, restarting at each GT segment
    so capacity-change boundaries keep their first observation.
    """
    if sample_stride < 1:
        raise ValueError("sample_stride must be positive")
    fps = label["fps"]
    frames = video_frames(
        VIDEO_ROOT / label["video"], fps=fps, frame_count=label["decoded_frame_count"], predecoded=predecoded
    )
    detector, settings = HpDetector(), HpDetectionSettings()
    tolerance = annotations()["tolerance_px"]
    frame_index = accepted = rejected = 0
    labelled_frames = 0
    next_sample = 0.0
    sample_index = 0
    rejection_start = first_accepted = None
    longest_rejection = max_error = 0.0
    mistakes: list[dict] = []
    predictions: list[int] = []
    detector_costs: list[float] = []
    labelled_costs: list[float] = []
    source_start = float(label.get("source_start_seconds", 0.0))
    has_segments = bool(label.get("gt_segments"))
    gt_segments = label.get("gt_segments") or [
        {
            "source_start_seconds": source_start,
            "source_end_seconds": source_start + label["decoded_frame_count"] / fps,
            "gt_length_px": label["gt_length_px"],
        }
    ]
    segment_reports = [
        {
            "source_start_seconds": segment["source_start_seconds"],
            "source_end_seconds": segment["source_end_seconds"],
            "gt_length_px": segment["gt_length_px"],
            "accepted": 0,
            "rejected": 0,
            "incorrect": 0,
            "max_error_px": 0.0,
        }
        for segment in gt_segments
    ]
    active_segment_index: int | None = None
    gt_origin_x = float(label.get("gt_origin_x", 0.0))
    scale = 1.0
    try:
        for bgr in frames:
            timestamp = frame_index / fps
            source_timestamp = source_start + timestamp
            frame_index += 1

            segment_index = next(
                (
                    index
                    for index, segment in enumerate(gt_segments)
                    if segment["source_start_seconds"] <= source_timestamp < segment["source_end_seconds"]
                ),
                None,
            )
            if segment_index != active_segment_index:
                if active_segment_index is not None and rejection_start is not None:
                    previous_end = gt_segments[active_segment_index]["source_end_seconds"]
                    longest_rejection = max(longest_rejection, previous_end - rejection_start)
                active_segment_index = segment_index
                rejection_start = None
                next_sample = timestamp
                sample_index = 0
            if segment_index is not None:
                labelled_frames += 1
            if timestamp + 1e-9 < next_sample:
                continue
            next_sample = timestamp + interval_seconds
            sample_index += 1
            if (sample_index - 1) % sample_stride:
                continue
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            if augmentation is not None:
                transformed = augmentation.apply(Image.fromarray(rgb))
                scale = transformed.width / rgb.shape[1]
                rgb = np.asarray(transformed)
            start = perf_counter()
            length = estimate_boundary(rgb).length if single_frame else detector.detect(rgb, settings)
            detector_costs.append((perf_counter() - start) * 1000)
            if segment_index is None:
                continue
            labelled_costs.append(detector_costs[-1])
            if length is None:
                rejected += 1
                segment_reports[segment_index]["rejected"] += 1
                if rejection_start is None:
                    rejection_start = source_timestamp
                continue
            accepted += 1
            segment_reports[segment_index]["accepted"] += 1
            if first_accepted is None:
                first_accepted = source_timestamp
            if rejection_start is not None:
                longest_rejection = max(longest_rejection, source_timestamp - rejection_start)
                rejection_start = None
            measured_length = length - gt_origin_x * scale
            predictions.append(measured_length)
            gt_length = gt_segments[segment_index]["gt_length_px"] * scale
            error = abs(measured_length - gt_length)
            max_error = max(max_error, error)
            segment_reports[segment_index]["max_error_px"] = max(
                segment_reports[segment_index]["max_error_px"], error
            )
            if error > tolerance * scale:
                segment_reports[segment_index]["incorrect"] += 1
                mistakes.append(
                    {
                        "frame": frame_index - 1,
                        "source_seconds": source_timestamp,
                        "length": measured_length,
                        "gt_length_px": gt_length,
                    }
                )
    finally:
        frames.close()
    if rejection_start is not None:
        active_end = gt_segments[active_segment_index]["source_end_seconds"]
        longest_rejection = max(longest_rejection, active_end - rejection_start)
    if frame_index != label["decoded_frame_count"]:
        raise AssertionError(f"Decoded {frame_index} frames; expected {label['decoded_frame_count']}")
    if not labelled_costs:
        raise AssertionError("No frames were evaluated")
    return {
        "id": label["id"],
        "algorithm": "single_frame_baseline" if single_frame else "structural",
        "augmentation": augmentation.name if augmentation else "original",
        "interval_seconds": interval_seconds,
        "sample_stride": sample_stride,
        "detector_calls": len(detector_costs),
        "decoded_frames": frame_index,
        "evaluated_frames": len(labelled_costs),
        "gt_length_px": (label["gt_length_px"] * scale if not has_segments else label.get("gt_length_px")),
        "gt_segments": segment_reports,
        "ignored_frames": frame_index - labelled_frames,
        "tolerance_px": tolerance * scale,
        "width_scale": scale,
        "prediction_range_px": [min(predictions), max(predictions)] if predictions else None,
        "accepted": accepted,
        "rejected": rejected,
        "rejection_ratio": rejected / len(labelled_costs),
        "incorrect": len(mistakes),
        "mistake_examples": mistakes[:10],
        "max_error_px": max_error,
        "first_accepted_seconds": first_accepted,
        "longest_rejection_seconds": longest_rejection,
        "detector_ms": {
            "mean": float(np.mean(detector_costs)),
            "p95": float(np.percentile(detector_costs, 95)),
            "max": max(detector_costs),
        },
    }
