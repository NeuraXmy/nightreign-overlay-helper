"""Stable repository and capture paths independent of a test module location."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAP_CAPTURE_DIR = PROJECT_ROOT / "tests/data/map_detect"
