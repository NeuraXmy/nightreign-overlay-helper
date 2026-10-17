"""Evaluate complex-background footage with the production calibration and crop geometry."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
from PyQt6.QtCore import QRect

from nightreign_overlay.plugins.hp_marker.config import HpDetectionSettings
from nightreign_overlay.plugins.hp_marker.detector import HpDetector
from nightreign_overlay.plugins.hp_marker.material import estimate_material_boundary
from nightreign_overlay.plugins.hp_marker.plugin import _detection_region
from tests.support.hp_rectangle import RectangleHpExperiment
from tests.support.hp_video import VIDEO_ROOT


def scene_labels() -> list[dict]:
    return json.loads((VIDEO_ROOT / "scene_annotations.json").read_text(encoding="utf-8"))["annotations"]


def scene_geometry(label: dict) -> tuple[QRect, QRect, int]:
    calibration = QRect(*label["calibration_xywh"])
    crop = _detection_region(calibration, HpDetectionSettings(), QRect(0, 0, *label["source_size_px"]))
    fixture = QRect(*label["fixture_crop_xywh"])
    if not fixture.contains(crop):
        raise ValueError("Fixture omits pixels required by production capture")
    return (
        crop,
        crop.translated(-fixture.x(), -fixture.y()),
        calibration.y() - crop.y() + calibration.height() // 2,
    )


def evaluate_scene(
    label: dict,
    *,
    source: Path | None = None,
    intervals: tuple[float, ...] = (0, 0.05, 0.25),
    geometry_only: bool = False,
) -> dict:
    """GT is consulted after detection; all intervals start with fresh detectors."""
    if geometry_only and label["contains_limit_loss_gray"]:
        raise ValueError("Outer geometry alone cannot measure usable capacity in gray footage")
    path = VIDEO_ROOT / label["video"] if source is None else source
    expected_hash = label["video_sha256"] if source is None else label["source_sha256"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("Video does not match the independently labelled footage")
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError("Cannot decode source video")
    fps = capture.get(cv2.CAP_PROP_FPS)
    settings = HpDetectionSettings()
    # Simulates the same tight, left-aligned selection as the production UI.
    calibration = QRect(*label["calibration_xywh"])
    crop, fixture_view, scanline_y = scene_geometry(label)
    view_rect = fixture_view if source is None else crop
    if fps != label["fps"]:
        capture.release()
        raise ValueError("Unexpected video frame rate")
    states = [
        {
            "detector": RectangleHpExperiment() if geometry_only else HpDetector(),
            "interval_seconds": interval,
            "next_sample": 0.0,
            "evaluated": 0,
            "rejected": 0,
            "incorrect": 0,
            "rejection_start": None,
            "longest_rejection_seconds": 0.0,
            "lengths": [],
            "costs": [],
            "mistakes": [],
            "false_gray_samples": 0,
            "wrong_outer_samples": 0,
        }
        for interval in intervals
    ]
    frame_index = 0
    try:
        while True:
            ok, bgr = capture.read()
            if not ok:
                break
            timestamp = frame_index / fps
            view = bgr[
                view_rect.y() : view_rect.y() + view_rect.height(),
                view_rect.x() : view_rect.x() + view_rect.width(),
            ]
            rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
            for state in states:
                if timestamp + 1e-9 < state["next_sample"]:
                    continue
                state["next_sample"] = timestamp + state["interval_seconds"]
                start = perf_counter()
                length = (
                    state["detector"].detect(rgb)
                    if geometry_only
                    else state["detector"].detect(
                        rgb, settings, scanline_y=scanline_y, bar_height=calibration.height()
                    )
                )
                state["costs"].append(1000 * (perf_counter() - start))
                state["evaluated"] += 1
                if length is None:
                    state["rejected"] += 1
                    if state["rejection_start"] is None:
                        state["rejection_start"] = timestamp
                    continue
                if state["rejection_start"] is not None:
                    state["longest_rejection_seconds"] = max(
                        state["longest_rejection_seconds"], timestamp - state["rejection_start"]
                    )
                    state["rejection_start"] = None
                state["lengths"].append(length)
                if abs(length - label["gt_length_px"]) <= label["tolerance_px"]:
                    continue
                state["incorrect"] += 1
                material = (
                    None
                    if geometry_only
                    else estimate_material_boundary(
                        rgb, scanline_y=scanline_y, bar_height=calibration.height()
                    )
                )
                outer = None if material is None else material.outer
                usable = None if material is None else material.usable
                if outer is not None and abs(outer - label["gt_length_px"]) <= label["tolerance_px"]:
                    state["false_gray_samples"] += 1
                else:
                    state["wrong_outer_samples"] += 1
                state["mistakes"].append(
                    {
                        "frame": frame_index,
                        "seconds": timestamp,
                        "length": length,
                        "material_outer": outer,
                        "material_usable": usable,
                    }
                )
            frame_index += 1
    finally:
        capture.release()
    if frame_index != label["decoded_frame_count"]:
        raise AssertionError(f"Decoded {frame_index}, expected {label['decoded_frame_count']}")
    reports = []
    for state in states:
        if state["rejection_start"] is not None:
            state["longest_rejection_seconds"] = max(
                state["longest_rejection_seconds"], frame_index / fps - state["rejection_start"]
            )
        lengths, costs = state.pop("lengths"), state.pop("costs")
        state.pop("detector")
        state.pop("next_sample")
        state.pop("rejection_start")
        state["rejection_ratio"] = state["rejected"] / state["evaluated"]
        state["prediction_range_px"] = [min(lengths), max(lengths)] if lengths else None
        state["detector_ms"] = {"mean": float(np.mean(costs)), "p95": float(np.percentile(costs, 95))}
        reports.append(state)
    return {
        "id": label["id"],
        "algorithm": "rectangle_experiment" if geometry_only else "production",
        "source_file": label["source_file"],
        "source_sha256": label["source_sha256"],
        "decoded_frames": frame_index,
        "fps": fps,
        "calibration_xywh": calibration.getRect(),
        "capture_xywh": crop.getRect(),
        "scanline_y_in_crop": scanline_y,
        "gt_length_px": label["gt_length_px"],
        "tolerance_px": label["tolerance_px"],
        "contains_limit_loss_gray": False,
        "reports": reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir", type=Path, help="Optionally verify original sources instead of lossless fixtures"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--geometry-only",
        action="store_true",
        help="Compare the existing outer-only experiment; not a usable-capacity detector",
    )
    args = parser.parse_args()
    result = [
        evaluate_scene(
            label,
            source=None if args.source_dir is None else args.source_dir / label["source_file"],
            geometry_only=args.geometry_only,
        )
        for label in scene_labels()
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
