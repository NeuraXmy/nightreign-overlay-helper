"""Reproduce original, augmented and independent-start capacity evaluations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from nightreign_overlay.plugins.hp_marker.config import HpDetectionSettings
from nightreign_overlay.plugins.hp_marker.detector import HpDetector
from nightreign_overlay.plugins.hp_marker.material import MaterialModel
from tests.support.hp_augmentations import augmentations
from tests.support.hp_video import VIDEO_ROOT, evaluate_video, hp_footage_annotations


def evaluate_starts(label: dict, *, model: MaterialModel | None = None) -> dict:
    """Fresh detectors at each labelled integer second with five seconds left."""
    capture = cv2.VideoCapture(str(VIDEO_ROOT / label["video"]))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot decode fixture: {label['video']}")
    frames = []
    try:
        while True:
            ok, bgr = capture.read()
            if not ok:
                break
            frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    finally:
        capture.release()
    fps = label["fps"]
    step = round(0.25 * fps)
    windows = []
    model = model or MaterialModel()
    for segment in label["gt_segments"]:
        for second in range(int(segment["source_start_seconds"]), int(segment["source_end_seconds"]) - 4):
            detector, settings = HpDetector(material_model=model), HpDetectionSettings()
            start = round((second - label["source_start_seconds"]) * fps)
            outputs = [
                detector.detect(frame, settings) for frame in frames[start : start + round(5 * fps) : step]
            ]
            incorrect = sum(
                value is not None and abs(value - label["gt_origin_x"] - segment["gt_length_px"]) > 3
                for value in outputs
            )
            first = next(
                (index * step / fps for index, value in enumerate(outputs) if value is not None), None
            )
            windows.append(
                {
                    "source_start_seconds": second,
                    "incorrect": incorrect,
                    "rejection_ratio": sum(value is None for value in outputs) / len(outputs),
                    "first_accepted_after_seconds": first,
                }
            )
    return {"id": label["id"], "sampling_period_seconds": step / fps, "windows": windows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    labels = hp_footage_annotations()["annotations"]
    report = {
        "original": [
            evaluate_video(label, interval_seconds=interval)
            for interval in (0, 0.05, 0.25)
            for label in labels
        ],
        "independent_starts": [evaluate_starts(label) for label in labels],
        "augmented": [
            evaluate_video(label, interval_seconds=0.25, augmentation=variant)
            for label in labels
            for variant in augmentations()
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
