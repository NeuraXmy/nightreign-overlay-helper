"""Measure full-map detection on captures and deterministic positive/negative transforms."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageEnhance, ImageFilter  # noqa: E402
from PIL import __version__ as pillow_version  # noqa: E402

from nightreign_overlay.plugins.map_detect.detector import MapDetector  # noqa: E402

log = logging.getLogger("benchmark_full_map")
EXCLUDED_CAPTURES = frozenset({"12.jpg", "1137_2.jpg", "207_hide.jpg"})


def variants(image: Image.Image) -> Iterator[tuple[str, str, bool, Image.Image]]:
    """Yield group, reproducible transform name, ground truth and RGB pixels.

    Color/filter transforms operate independently on the original except the two
    explicitly named combinations. Alpha uses encoded RGB blending, as PIL does.
    Crop fractions describe side lengths, with square/rectangular aspect preserved.
    """
    yield "original", "original", True, image
    for name, enhancer, factors in (
        ("saturation", ImageEnhance.Color, (0.1, 0.3, 2.0, 3.0)),
        ("brightness", ImageEnhance.Brightness, (0.35, 0.6, 1.5, 2.0)),
        ("contrast", ImageEnhance.Contrast, (0.35, 0.6, 1.8, 2.5)),
        ("sharpness", ImageEnhance.Sharpness, (1.8, 3.0)),
    ):
        for factor in factors:
            yield "enhanced", f"{name}_{factor:g}", True, enhancer(image).enhance(factor)
    for radius in (0.5, 1.0):
        yield "enhanced", f"blur_{radius:g}px", True, image.filter(ImageFilter.GaussianBlur(radius))
    for saturation, contrast, brightness in ((0.3, 0.6, 0.6), (2.0, 1.8, 1.5)):
        enhanced = ImageEnhance.Color(image).enhance(saturation)
        enhanced = ImageEnhance.Contrast(enhanced).enhance(contrast)
        enhanced = ImageEnhance.Brightness(enhanced).enhance(brightness)
        name = f"combined_s{saturation:g}_c{contrast:g}_b{brightness:g}"
        yield "enhanced", name, True, enhanced

    for background, color in (
        ("black", (0, 0, 0)),
        ("gray", (128, 128, 128)),
        ("white", (255, 255, 255)),
        ("red", (180, 40, 40)),
        ("green", (40, 180, 40)),
        ("blue", (40, 40, 180)),
    ):
        backdrop = Image.new("RGB", image.size, color)
        for alpha in (0.1, 0.25, 0.4, 0.49):
            yield "transparent", f"alpha_{alpha:g}_{background}", False, Image.blend(backdrop, image, alpha)

    width, height = image.size
    for fraction in (0.5, 0.75, 0.9):
        crop_width, crop_height = round(width * fraction), round(height * fraction)
        for anchor, x_factor, y_factor in (
            ("center", 0.5, 0.5),
            ("top_left", 0, 0),
            ("top_right", 1, 0),
            ("bottom_left", 0, 1),
            ("bottom_right", 1, 1),
        ):
            x = round((width - crop_width) * x_factor)
            y = round((height - crop_height) * y_factor)
            cropped = image.crop((x, y, x + crop_width, y + crop_height))
            yield (
                "cropped",
                f"crop_{fraction:g}_{anchor}",
                False,
                cropped.resize(image.size, Image.Resampling.LANCZOS),
            )


def summarize(rows: list[dict]) -> dict:
    correct = sum(row["correct"] for row in rows)
    return {
        "count": len(rows),
        "correct": correct,
        "accuracy": correct / len(rows),
        "false_positive": sum(not row["expected"] and row["predicted"] for row in rows),
        "false_negative": sum(row["expected"] and not row["predicted"] for row in rows),
    }


def benchmark(captures: Path) -> dict:
    paths = sorted(path for path in captures.glob("*.jpg") if path.name not in EXCLUDED_CAPTURES)
    if not paths:
        raise ValueError(f"No JPEG captures found in {captures}")
    detector = MapDetector()
    rows, sources = [], []
    grouped, transforms, per_capture = defaultdict(list), defaultdict(list), defaultdict(list)
    for path in paths:
        with Image.open(path) as source:
            image = source.convert("RGB")
        sources.append(
            {
                "capture": path.name,
                "size": list(image.size),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
        for group, name, expected, transformed in variants(image):
            # Preserve RGB input and the exact default threshold comparison used
            # by MapDetector.detect; all preprocessing belongs to the matcher.
            error = float(detector._match_full_map(np.array(transformed)))
            predicted = error <= detector.config.full_map_error_threshold
            row = {
                "capture": path.name,
                "group": group,
                "transform": name,
                "expected": expected,
                "predicted": predicted,
                "correct": predicted == expected,
                "error": error if math.isfinite(error) else None,
            }
            rows.append(row)
            grouped[group].append(row)
            transforms[name].append(row)
            per_capture[path.name].append(row)
        log.info("Evaluated %s", path.name)
    return {
        "excluded_captures": sorted(EXCLUDED_CAPTURES),
        "exclusion_reason": "These captures already contain image enhancement.",
        "settings": asdict(detector.config),
        "versions": {"opencv": cv2.__version__, "numpy": np.__version__, "pillow": pillow_version},
        "sources": sources,
        "summary": summarize(rows),
        "by_group": {name: summarize(values) for name, values in grouped.items()},
        "by_transform": {name: summarize(values) for name, values in transforms.items()},
        "by_capture": {
            name: {group: summarize([row for row in values if row["group"] == group]) for group in grouped}
            for name, values in per_capture.items()
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, default=ROOT / "tests/data/map_detect")
    parser.add_argument("--output", type=Path, default=ROOT / ".tmp/full_map_benchmark.json")
    parser.add_argument(
        "--fail-on-error", action="store_true", help="Exit with status 1 on any misclassification"
    )
    args = parser.parse_args()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    report = benchmark(args.captures)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    for group, summary in {"total": report["summary"], **report["by_group"]}.items():
        log.info(
            "%s: %d/%d (%.2f%%), FP=%d FN=%d",
            group,
            summary["correct"],
            summary["count"],
            summary["accuracy"] * 100,
            summary["false_positive"],
            summary["false_negative"],
        )
    log.info("Report: %s", args.output)
    if args.fail_on_error and report["summary"]["correct"] != report["summary"]["count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
