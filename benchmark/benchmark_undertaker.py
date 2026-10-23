"""Measure Undertaker detection accuracy and latency on icon regression samples."""

from __future__ import annotations

import argparse
import json
import logging
import platform
import sys
from itertools import chain
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from tests.support.undertaker_images import combined_variants, legacy_variants  # noqa: E402

from nightreign_overlay.core.images import read_cv2_image  # noqa: E402
from nightreign_overlay.plugins.art_timer.undertaker_detector import is_active  # noqa: E402

log = logging.getLogger(__name__)


def benchmark(captures: Path, repeats: int) -> dict:
    paths = sorted(captures.glob("*.png"))
    if not paths:
        raise ValueError(f"No icon samples in {captures}")
    rows = []
    for path in paths:
        rgb = cv2.cvtColor(read_cv2_image(path), cv2.COLOR_BGR2RGB)
        for parameters, image in chain(legacy_variants(rgb), combined_variants(rgb)):
            for repeat in range(repeats):
                # Include resizing and HSV conversion; exclude image generation.
                start = perf_counter()
                active = is_active(image)
                elapsed = (perf_counter() - start) * 1000
                rows.append(
                    {
                        "file": path.name,
                        "variant": str(parameters),
                        "repeat": repeat,
                        "expected": path.name == "0.png",
                        "active": active,
                        "ms": elapsed,
                    }
                )
    times = [row["ms"] for row in rows]
    return {
        "python": platform.python_version(),
        "opencv": cv2.__version__,
        "samples": len(paths),
        "calls": len(rows),
        "errors": [row for row in rows if row["expected"] != row["active"]],
        "median_ms": float(np.median(times)),
        "p95_ms": float(np.percentile(times, 95)),
        "max_ms": max(times),
        "over_20ms": sum(value > 20 for value in times),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, default=ROOT / "tests/data/undertaker_art")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / ".tmp/undertaker-benchmark.json")
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
