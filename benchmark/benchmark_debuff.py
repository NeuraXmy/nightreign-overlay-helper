"""Check meter detection accuracy and latency on the regression corpus."""

from __future__ import annotations

import argparse
import json
import logging
import platform
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from tests.support.debuff_images import combined_variants, variants  # noqa: E402

from nightreign_overlay.plugins.debuff_timer.detector import DebuffDetector  # noqa: E402

log = logging.getLogger(__name__)


def benchmark(captures: Path, repeats: int) -> dict:
    detector = DebuffDetector()
    rows = []

    def measure(detector, rgb, path, variant, repeat):
        # Decoding, augmentation and construction are outside detect's budget.
        started = perf_counter()
        result = detector.detect(rgb)
        elapsed_ms = (perf_counter() - started) * 1000
        rows.append(
            {
                "file": path.name,
                "variant": variant,
                "repeat": repeat,
                "expected": not path.stem.startswith("None"),
                "present": result.present,
                "ms": elapsed_ms,
            }
        )

    paths = sorted(captures.glob("*.png"))
    if not paths:
        raise ValueError(f"No regression images in {captures}")
    for path in paths:
        rgb = cv2.cvtColor(
            cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB
        )
        measure(DebuffDetector(), rgb, path, "first_call", 0)
        for index, image in enumerate(variants(rgb)):
            for repeat in range(repeats):
                measure(detector, image, path, f"single_{index}", repeat)
        for parameters, image in combined_variants(rgb):
            for repeat in range(repeats):
                measure(detector, image, path, f"combined_{parameters}", repeat)
    times = [row["ms"] for row in rows]
    return {
        "python": platform.python_version(),
        "opencv": cv2.__version__,
        "opencv_threads": cv2.getNumThreads(),
        "samples": len(paths),
        "calls": len(rows),
        "errors": [row for row in rows if row["expected"] != row["present"]],
        "median_ms": float(np.median(times)),
        "p95_ms": float(np.percentile(times, 95)),
        "max_ms": max(times),
        "over_20ms": sum(t > 20 for t in times),
        "slowest": sorted(rows, key=lambda row: row["ms"], reverse=True)[:10],
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, default=ROOT / "tests/data/debuff")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--output", type=Path, default=ROOT / ".tmp/debuff-benchmark.json")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    result = benchmark(args.captures, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info("%s", json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2))
    return int(bool(result["errors"]) or result["over_20ms"] > 0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
