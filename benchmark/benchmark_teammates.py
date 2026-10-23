"""Measure complete teammate classification accuracy and per-call latency."""

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
from tests.support.teammate_images import expected_states, sample_paths, states, variants  # noqa: E402

from nightreign_overlay.core.images import read_cv2_image  # noqa: E402
from nightreign_overlay.plugins.entertainment.detector import detect_rgb  # noqa: E402


def benchmark(captures: Path, repeats: int) -> dict:
    paths = sample_paths(captures)
    if not paths:
        raise ValueError(f"No teammate samples in {captures}")
    rows = []
    for path in paths:
        rgb = cv2.cvtColor(read_cv2_image(path), cv2.COLOR_BGR2RGB)
        expected = expected_states(path)
        for parameters, image in variants(rgb):
            for repeat in range(repeats):
                start = perf_counter()
                result = detect_rgb(image)
                elapsed = (perf_counter() - start) * 1000
                rows.append(
                    {
                        "file": str(path.relative_to(captures)),
                        "variant": str(parameters),
                        "repeat": repeat,
                        "expected": expected,
                        "actual": states(result),
                        "ms": elapsed,
                    }
                )
    times = [row["ms"] for row in rows]
    return {
        "python": platform.python_version(),
        "opencv": cv2.__version__,
        "samples": len(paths),
        "calls": len(rows),
        "errors": [row for row in rows if row["expected"] != row["actual"]],
        "median_ms": float(np.median(times)),
        "p95_ms": float(np.percentile(times, 95)),
        "max_ms": max(times),
        "over_20ms": sum(t > 20 for t in times),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, default=ROOT / "tests/data/entertainment")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / ".tmp/teammate-benchmark.json")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    result = benchmark(args.captures, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logging.info("%s", json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    return int(bool(result["errors"]) or result["over_20ms"] > 0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
