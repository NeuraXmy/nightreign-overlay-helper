"""Resolve self-contained map assets and legacy diagnostic output paths."""

from __future__ import annotations

from pathlib import Path

from nightreign_overlay.core.paths import user_data_dir


def get_data_path(path: str) -> str:
    return str(Path(__file__).parent / "data" / path)


def get_appdata_path(filename: str) -> str:
    return str(user_data_dir() / filename)
