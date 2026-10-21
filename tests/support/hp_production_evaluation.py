"""Evaluate all four original-context videos, continuous playback and independent starts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

from nightreign_overlay.plugins.hp_marker.config import HpDetectionSettings
from nightreign_overlay.plugins.hp_marker.detector import HpDetector
from nightreign_overlay.plugins.hp_marker.material import MaterialModel
from tests.support.hp_scene_evaluation import scene_geometry
from tests.support.hp_video import VIDEO_ROOT


def production_labels() -> list[dict]:
    return json.loads((VIDEO_ROOT / "production_annotations.json").read_text(encoding="utf-8"))["annotations"]


def heldout_block_label(label: dict) -> dict:
    """Score only alternating five-second blocks excluded by the training tool."""
    segments = []
    for part in label["gt_segments"]:
        for block in range(
            math.floor(part["source_start_seconds"] / 5), math.ceil(part["source_end_seconds"] / 5)
        ):
            start = max(part["source_start_seconds"], block * 5)
            end = min(part["source_end_seconds"], (block + 1) * 5)
            if block % 2 and start < end:
                segments.append(dict(part, source_start_seconds=start, source_end_seconds=end))
    return dict(label, gt_segments=segments)


@dataclass
class _Run:
    interval_seconds: float
    start_seconds: float
    end_seconds: float
    detector: HpDetector = field(default_factory=HpDetector)
    next_sample: float = field(init=False)
    evaluated: int = 0
    rejected: int = 0
    calls: int = 0
    first_accepted: float | None = None
    rejection_start: float | None = None
    segment_end: float | None = None
    longest_rejection: float = 0
    mistakes: list[dict] = field(default_factory=list)
    lengths: list[int] = field(default_factory=list)
    costs: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.next_sample = self.start_seconds

    def close_rejection(self, timestamp: float) -> None:
        if self.rejection_start is not None:
            self.longest_rejection = max(self.longest_rejection, timestamp - self.rejection_start)
            self.rejection_start = None

    def consume(
        self,
        rgb: np.ndarray,
        frame_index: int,
        timestamp: float,
        scanline_y: int,
        bar_height: int,
        settings: HpDetectionSettings,
        segment: dict | None,
        tolerance: int,
    ) -> None:
        if timestamp + 1e-9 < self.next_sample or timestamp >= self.end_seconds:
            return
        self.next_sample = timestamp + self.interval_seconds
        started = perf_counter()
        # No GT, video identity, timestamps or capacity-constant flag enters detection.
        length = self.detector.detect(rgb, settings, scanline_y=scanline_y, bar_height=bar_height)
        self.costs.append(1000 * (perf_counter() - started))
        self.calls += 1
        if self.segment_end is not None and (segment is None or timestamp >= self.segment_end):
            self.close_rejection(min(self.end_seconds, self.segment_end))
            self.segment_end = None
        if segment is None:
            return
        self.segment_end = segment["source_end_seconds"]
        self.evaluated += 1
        if length is None:
            self.rejected += 1
            if self.rejection_start is None:
                self.rejection_start = timestamp
            return
        self.close_rejection(timestamp)
        if self.first_accepted is None:
            self.first_accepted = timestamp - self.start_seconds
        self.lengths.append(length)
        error = length - segment["gt_length_px"]
        if abs(error) > tolerance:
            self.mistakes.append(
                {"frame": frame_index, "seconds": timestamp, "length": length, "error_px": error}
            )

    def report(self) -> dict:
        self.close_rejection(min(self.end_seconds, self.segment_end or self.end_seconds))
        return {
            "interval_seconds": self.interval_seconds,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "detector_calls": self.calls,
            "evaluated": self.evaluated,
            "incorrect": len(self.mistakes),
            "rejected": self.rejected,
            "rejection_ratio": self.rejected / self.evaluated if self.evaluated else None,
            "longest_rejection_seconds": self.longest_rejection,
            "first_accepted_after_seconds": self.first_accepted,
            "prediction_range_px": [min(self.lengths), max(self.lengths)] if self.lengths else None,
            "mistakes": self.mistakes,
            "detector_ms": {
                "mean": float(np.mean(self.costs)),
                "p95": float(np.percentile(self.costs, 95)),
            }
            if self.costs
            else None,
        }


def evaluate_production(
    label: dict,
    *,
    source: Path | None = None,
    intervals: tuple[float, ...] = (0, 0.05, 0.25),
    cold_starts: bool = True,
    model: MaterialModel | None = None,
) -> dict:
    """Decode once; each run owns a fresh detector, and ignored frames still feed continuous runs."""
    path = VIDEO_ROOT / label["video"] if source is None else source
    expected_hash = label["video_sha256"] if source is None else label["source_sha256"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("Video hash differs from the independently labelled source")
    crop, view, scanline_y = scene_geometry(label)
    if source is not None:
        view = crop
    duration = label["decoded_frame_count"] / label["fps"]
    continuous = [_Run(interval, 0, duration) for interval in intervals]
    starts = []
    if cold_starts:
        for segment in label["gt_segments"]:
            for start in range(
                math.ceil(segment["source_start_seconds"]),
                math.floor(segment["source_end_seconds"] - 5) + 1,
            ):
                starts.append(_Run(0.25, start, start + 5))
    model = model or MaterialModel()
    for run in continuous + starts:
        run.detector = HpDetector(material_model=model)
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open {path.name}")
    settings = HpDetectionSettings()
    frame_index = 0
    try:
        if capture.get(cv2.CAP_PROP_FPS) != label["fps"]:
            raise ValueError("Video frame rate differs from annotation")
        while True:
            ok, bgr = capture.read()
            if not ok:
                break
            timestamp = frame_index / label["fps"]
            selected = [
                run
                for run in continuous + starts
                if run.start_seconds <= timestamp < run.end_seconds and timestamp + 1e-9 >= run.next_sample
            ]
            if selected:
                rgb = cv2.cvtColor(
                    bgr[view.y() : view.y() + view.height(), view.x() : view.x() + view.width()],
                    cv2.COLOR_BGR2RGB,
                )
                segment = next(
                    (
                        part
                        for part in label["gt_segments"]
                        if part["source_start_seconds"] <= timestamp < part["source_end_seconds"]
                    ),
                    None,
                )
                for run in selected:
                    run.consume(
                        rgb,
                        frame_index,
                        timestamp,
                        scanline_y,
                        label["calibration_xywh"][3],
                        settings,
                        segment,
                        label["tolerance_px"],
                    )
            frame_index += 1
    finally:
        capture.release()
    if frame_index != label["decoded_frame_count"]:
        raise AssertionError(f"Decoded {frame_index} frames, expected {label['decoded_frame_count']}")
    windows = [run.report() for run in starts]
    return {
        "id": label["id"],
        "source_file": label["source_file"],
        "source_sha256": label["source_sha256"],
        "decoded_frame_count": frame_index,
        "fps": label["fps"],
        "calibration_xywh": label["calibration_xywh"],
        "capture_xywh": crop.getRect(),
        "continuous": [run.report() for run in continuous],
        "cold_starts": windows,
        "cold_start_summary": {
            "windows": len(windows),
            "incorrect": sum(window["incorrect"] for window in windows),
            "worst_rejection_ratio": max((window["rejection_ratio"] for window in windows), default=None),
            "slowest_first_output_seconds": max(
                (window["first_accepted_after_seconds"] or 0 for window in windows), default=None
            ),
            "windows_without_output": sum(
                window["first_accepted_after_seconds"] is None for window in windows
            ),
        },
    }


def evaluate_production_smoke(label: dict) -> list[dict]:
    """Sample three-second windows at segment starts and the final segment's tail.

    Decode only 12 real frames per window, using independent production detectors.
    Full playback, all sampling rates and exhaustive cold starts remain a benchmark.
    """
    path = VIDEO_ROOT / label["video"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != label["video_sha256"]:
        raise ValueError("Video hash differs from the independently labelled source")
    _, view, scanline_y = scene_geometry(label)
    segments = label["gt_segments"]
    starts = sorted(
        {part["source_start_seconds"] for part in segments} | {segments[-1]["source_end_seconds"] - 3}
    )
    model = MaterialModel()
    settings = HpDetectionSettings()
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened() or capture.get(cv2.CAP_PROP_FPS) != label["fps"]:
            raise ValueError("Cannot open annotated video at expected FPS")
        reports = []
        for start in starts:
            run = _Run(0.25, start, start + 3, detector=HpDetector(material_model=model))
            for index in range(12):
                frame_index = round((start + index * 0.25) * label["fps"])
                timestamp = frame_index / label["fps"]
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, bgr = capture.read()
                if not ok:
                    raise ValueError(f"Cannot decode frame {frame_index}")
                rgb = cv2.cvtColor(
                    bgr[view.y() : view.y() + view.height(), view.x() : view.x() + view.width()],
                    cv2.COLOR_BGR2RGB,
                )
                segment = next(
                    part
                    for part in segments
                    if part["source_start_seconds"] <= timestamp < part["source_end_seconds"]
                )
                # Seeking rounds sampling timestamps to real frames; avoid using
                # _Run's interval gate, which could skip alternating 7/8-frame steps.
                run.next_sample = timestamp
                run.consume(
                    rgb,
                    frame_index,
                    timestamp,
                    scanline_y,
                    label["calibration_xywh"][3],
                    settings,
                    segment,
                    label["tolerance_px"],
                )
            reports.append(run.report())
        return reports
    finally:
        capture.release()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--skip-starts", action="store_true")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--heldout-blocks-only", action="store_true")
    args = parser.parse_args()
    labels = production_labels()
    if args.heldout_blocks_only:
        if args.model_dir is None:
            parser.error("Held-out scoring requires an explicit separately trained model directory")
        metadata = json.loads((args.model_dir / "training.json").read_text(encoding="utf-8"))
        if not metadata["holdout_alternating_five_second_blocks"]:
            parser.error("This model trained on the evaluation blocks")
        for item in metadata["provenance"]:
            for field in ("material_training_frame_indices", "cap_training_frame_indices"):
                if any(int(frame / 30 // 5) % 2 for frame in item[field]):
                    parser.error("Training provenance overlaps the evaluation blocks")
        labels = [heldout_block_label(label) for label in labels]
    model = MaterialModel(args.model_dir)
    results = [
        evaluate_production(
            label,
            source=None if args.source_dir is None else args.source_dir / label["source_file"],
            cold_starts=not args.skip_starts,
            model=model,
        )
        for label in labels
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")


if __name__ == "__main__":
    main()
