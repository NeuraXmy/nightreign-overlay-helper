"""Evaluate the experimental multirow detector on the expanded HP video fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tests.support.hp_rectangle import RectangleHpExperiment

from nightreign_overlay.plugins.hp_marker.tracking import StructuralHpDetector

DATA = Path(__file__).resolve().parents[1] / "tests/data/hp_detect/videos"


def summarize(predictions: list[int | None], timestamps: list[float], duration: float, gt: int) -> dict:
    values = np.array([-1 if value is None else value for value in predictions])
    valid = values >= 0
    errors = np.abs(values[valid] - gt)
    rejection_start, longest = None, 0.0
    for timestamp, accepted in zip(timestamps, valid, strict=True):
        if not accepted and rejection_start is None:
            rejection_start = timestamp
        elif accepted and rejection_start is not None:
            longest = max(longest, timestamp - rejection_start)
            rejection_start = None
    if rejection_start is not None:
        longest = max(longest, duration - rejection_start)
    return {
        "evaluated_frames": len(values),
        "accepted": int(valid.sum()),
        "rejected": int((~valid).sum()),
        "rejection_ratio": float((~valid).mean()),
        "incorrect": int((errors > 3).sum()),
        "max_error_px": int(errors.max()) if len(errors) else None,
        "prediction_range_px": [int(values[valid].min()), int(values[valid].max())] if valid.any() else None,
        "longest_rejection_seconds": longest,
        "first_accepted_seconds": next(
            (timestamp for timestamp, accepted in zip(timestamps, valid, strict=True) if accepted), None
        ),
        "mistake_examples": [
            {"seconds": timestamp, "length": int(value)}
            for timestamp, value in zip(timestamps, values, strict=True)
            if value >= 0 and abs(value - gt) > 3
        ][:10],
    }


def evaluate(frames: list[np.ndarray], label: dict, interval: float, *, baseline: bool = False) -> dict:
    detector = StructuralHpDetector() if baseline else RectangleHpExperiment()
    predictions, timestamps, costs = [], [], []
    next_sample = 0.0
    for index, frame in enumerate(frames):
        timestamp = index / label["fps"]
        if timestamp + 1e-9 < next_sample:
            continue
        next_sample += interval
        # The production baseline expects its left edge at the calibrated cap
        # and its middle row in the interior. The experiment receives margins.
        image = frame[7:18, 10:] if baseline else frame
        start = perf_counter()
        predictions.append(detector.detect(image))
        costs.append((perf_counter() - start) * 1000)
        timestamps.append(timestamp)
    report = summarize(predictions, timestamps, len(frames) / label["fps"], label["gt_length_px"])
    report.update(
        algorithm="production_scanline" if baseline else "experimental_multirow",
        interval_seconds=interval,
        detector_ms={
            "mean": float(np.mean(costs)),
            "p95": float(np.percentile(costs, 95)),
            "max": max(costs),
        },
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DATA / "rectangle_report.json")
    args = parser.parse_args()
    label = json.loads((DATA / "rectangle_annotations.json").read_text(encoding="utf-8"))
    capture = cv2.VideoCapture(str(DATA / label["video"]))
    frames = []
    try:
        while True:
            ok, bgr = capture.read()
            if not ok:
                break
            frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    finally:
        capture.release()
    if len(frames) != label["decoded_frame_count"]:
        raise RuntimeError(f"Decoded {len(frames)} frames; expected {label['decoded_frame_count']}")
    reports = [
        evaluate(frames, label, interval, baseline=baseline)
        for baseline in (True, False)
        for interval in (0, 0.05, 0.25)
    ]
    # A continuous run can hide acquisition failures when it happens to start
    # from a clear frame. Independently initialize at every whole second too.
    cold_starts = []
    fps = label["fps"]
    window = round(5 * fps)
    for index in range(0, len(frames) - window, round(fps)):
        detector = RectangleHpExperiment()
        predictions = [detector.detect(frame) for frame in frames[index : index + window]]
        summary = summarize(
            predictions, [i / fps for i in range(window)], window / fps, label["gt_length_px"]
        )
        cold_starts.append({"start_frame": index, **summary})
    result = {"continuous": reports, "independent_five_second_starts": cold_starts}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for report in reports:
        print(json.dumps(report, ensure_ascii=False))
    print(
        "Cold starts:",
        len(cold_starts),
        "with wrong predictions:",
        sum(bool(item["incorrect"]) for item in cold_starts),
        "with no predictions:",
        sum(not item["accepted"] for item in cold_starts),
    )
    return int(
        any(
            item["incorrect"] or item["rejection_ratio"] >= 0.2 or item["longest_rejection_seconds"] > 5
            for item in reports
            if item["algorithm"] == "experimental_multirow"
        )
        or any(item["incorrect"] or not item["accepted"] for item in cold_starts)
    )


if __name__ == "__main__":
    raise SystemExit(main())
