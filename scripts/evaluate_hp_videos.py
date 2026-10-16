"""Reproduce full-video HP accuracy, refusal and detector timing measurements."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tests.support.hp_augmentations import augmentations
from tests.support.hp_video import annotations, evaluate_video


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    parser.add_argument(
        "--augmentations", action="store_true", help="Also evaluate the same 32 full-frame transforms"
    )
    parser.add_argument(
        "--baseline", action="store_true", help="Also measure the prior single-frame estimator"
    )
    parser.add_argument(
        "--interval", type=float, default=0, help="Sampling interval in seconds; 0 tests every frame"
    )
    args = parser.parse_args()
    if args.interval < 0:
        parser.error("--interval must be nonnegative")
    labels = annotations()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    reports = []
    variants = [None, *augmentations()] if args.augmentations else [None]
    for variant in variants:
        for label in labels["annotations"]:
            report = evaluate_video(label, interval_seconds=args.interval, augmentation=variant)
            reports.append(report)
            logging.info(
                "%s %s: incorrect=%d refusal=%.2f%% longest=%.2fs",
                report["id"],
                report["augmentation"],
                report["incorrect"],
                report["rejection_ratio"] * 100,
                report["longest_rejection_seconds"],
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
    if args.baseline:
        reports += [
            evaluate_video(label, interval_seconds=args.interval, single_frame=True)
            for label in labels["annotations"]
        ]
    output = json.dumps(reports, ensure_ascii=False, indent=2) + "\n"
    logging.info("%s", output.rstrip())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    return int(
        any(
            report["incorrect"]
            or report["rejection_ratio"] > labels["max_rejection_ratio"]
            or report["longest_rejection_seconds"] > labels["max_rejection_seconds"]
            for report in reports
            if report["algorithm"] == "structural"
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
