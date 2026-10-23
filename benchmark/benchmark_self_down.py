"""Measure self-down classification on real icons, backgrounds and synthetic fill."""

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
from tests.support.self_down_samples import (  # noqa: E402
    continuous_variants,
    labeled_samples,
    legacy_variants,
    variants,
)

from nightreign_overlay.core.images import read_cv2_image  # noqa: E402
from nightreign_overlay.plugins.entertainment.self_detector import is_down  # noqa: E402


def cases(captures):
    for name, expected, rgb in labeled_samples(captures):
        for parameters, image in variants(rgb):
            yield name, parameters, expected, image
    for path in sorted((captures / "self_down").glob("down*.png")):
        rgb = cv2.cvtColor(read_cv2_image(path), cv2.COLOR_BGR2RGB)
        for parameters, image in legacy_variants(rgb):
            yield f"legacy/{path.name}", parameters, True, image
    rgb = cv2.cvtColor(read_cv2_image(captures / "self_down/down2.png"), cv2.COLOR_BGR2RGB)
    for parameters, image in continuous_variants(rgb):
        yield "synthetic-fill", parameters, True, image


def benchmark(captures: Path, repeats: int) -> dict:
    rows = []
    for name, parameters, expected, image in cases(captures):
        for repeat in range(repeats):
            start = perf_counter()
            actual = is_down(image)
            elapsed = (perf_counter() - start) * 1000
            rows.append(
                {
                    "file": name,
                    "variant": str(parameters),
                    "repeat": repeat,
                    "expected": expected,
                    "actual": actual,
                    "ms": elapsed,
                }
            )
    times = [row["ms"] for row in rows]
    return {
        "python": platform.python_version(),
        "opencv": cv2.__version__,
        "variants": len(rows) // repeats,
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
    parser.add_argument("--output", type=Path, default=ROOT / ".tmp/self-down-benchmark.json")
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
