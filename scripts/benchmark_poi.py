"""Compare production POI backends on labeled map captures, emitting JSON and a table."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import logging
import os
import platform
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# Keep production debug images out of the user's runtime directory.
os.environ.setdefault("NROH_DATA_DIR", tempfile.mkdtemp(prefix="poi-benchmark-"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from nightreign_overlay.plugins.map_detect.config import MapDetectionSettings  # noqa: E402
from nightreign_overlay.plugins.map_detect.detector import MapDetector  # noqa: E402


def benchmark(captures: Path, algorithms: list[str], excluded: set[str]) -> dict:
    """Recognize terrain/nightlord normally; labels are used only for scoring."""
    logging.disable(logging.INFO)
    rows = []
    for algorithm in algorithms:
        detector = MapDetector(MapDetectionSettings(poi_algorithm=algorithm))
        for path in sorted(captures.glob("*.jpg")):
            expected = [int(value) for value in path.stem.split("_")[0].split("-")]
            image = np.array(Image.open(path).convert("RGB"))
            random.seed(42)  # Identical point sampling and order for both algorithms.
            started = time.perf_counter()
            terrain, _ = detector._match_earth_shifting(image)
            results = detector._match_map_pattern(image, terrain, topk=len(detector.info.patterns))
            best = results[0]
            true_errors = [result.error for result in results if result.pattern.id in expected]
            rows.append(
                {
                    "algorithm": algorithm,
                    "capture": path.name,
                    "expected_ids": expected,
                    "predicted_id": best.pattern.id,
                    "correct": best.pattern.id in expected,
                    "included_in_acceptance": path.name not in excluded,
                    "poi_error": best.error,
                    "expected_poi_error": min(true_errors, default=None),
                    "earth_shifting": terrain,
                    "nightlord": best.nightlord,
                    "seconds": round(time.perf_counter() - started, 4),
                }
            )
    summary = {}
    for algorithm in algorithms:
        subset = [row for row in rows if row["algorithm"] == algorithm]
        correct = sum(row["correct"] for row in subset)
        within = sum(row["poi_error"] <= 10 for row in subset)
        accepted = [row for row in subset if row["included_in_acceptance"]]
        accepted_correct = sum(row["correct"] for row in accepted)
        accepted_within = sum(row["poi_error"] <= 10 for row in accepted)
        summary[algorithm] = {
            "count": len(subset),
            "correct": correct,
            "accuracy": correct / len(subset),
            "poi_error_le_10": within,
            "acceptance_count": len(accepted),
            "acceptance_correct": accepted_correct,
            "acceptance_accuracy": accepted_correct / len(accepted) if accepted else None,
            "acceptance_poi_error_le_10": accepted_within,
            "meets_target": bool(accepted)
            and accepted_correct == len(accepted)
            and accepted_within > len(accepted) / 2,
        }
    model = ROOT / "src/nightreign_overlay/plugins/map_detect/data/poi_cnn/epoch-42.onnx"
    metadata = {
        "python": platform.python_version(),
        "system": platform.platform(),
        "onnxruntime": importlib.metadata.version("onnxruntime") if "cnn" in algorithms else None,
        "numpy": np.__version__,
        "seed": 42,
        "excluded_from_acceptance": sorted(excluded),
        "sample_ratio_with_nightlord": 1.0,
        "sample_ratio_without_nightlord": 1.0,
        "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest() if "cnn" in algorithms else None,
    }
    return {"metadata": metadata, "summary": summary, "results": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, default=ROOT / "tests/data/map_detect")
    parser.add_argument("--algorithms", nargs="+", choices=["template", "cnn"], default=["template", "cnn"])
    parser.add_argument(
        "--exclude-from-acceptance",
        nargs="*",
        default=["207_hide.jpg"],
        metavar="FILENAME",
        help="Keep captures in report but exclude from acceptance (default: 207_hide.jpg)",
    )
    parser.add_argument("--output", type=Path, default=ROOT / ".tmp/poi_benchmark.json")
    args = parser.parse_args()
    if not list(args.captures.glob("*.jpg")):
        parser.error(f"No JPEG captures in {args.captures}")
    report = benchmark(args.captures, args.algorithms, set(args.exclude_from_acceptance))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        "algorithm | capture | expected | predicted | correct | acceptance | "
        "POI error | expected error | seconds"
    )
    for row in report["results"]:
        print(
            " | ".join(
                str(row[key])
                for key in (
                    "algorithm",
                    "capture",
                    "expected_ids",
                    "predicted_id",
                    "correct",
                    "included_in_acceptance",
                    "poi_error",
                    "expected_poi_error",
                    "seconds",
                )
            )
        )
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
