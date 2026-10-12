"""Filesystem locations for bundled resources and per-user data.

Bundled resources are resolved relative to the package so the same code works from source and from a
PyInstaller bundle (which preserves the package layout under ``sys._MEIPASS``).
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

from platformdirs import user_data_dir as _platform_user_data_dir

from nightreign_overlay.meta import APP_DATA_DIR_NAME

#: Environment variable that overrides the user data directory (handy for development and tests).
DATA_DIR_ENV = "NROH_DATA_DIR"

PACKAGE_DIR = Path(__file__).resolve().parent.parent
RESOURCES_DIR = PACKAGE_DIR / "resources"


def resource_path(*parts: str) -> Path:
    """Return the path of a bundled core resource, e.g. ``resource_path("icons", "app.ico")``."""
    return RESOURCES_DIR.joinpath(*parts)


@cache
def user_data_dir() -> Path:
    """Directory holding settings, logs and caches. Created on first access."""
    override = os.environ.get(DATA_DIR_ENV)
    path = (
        Path(override)
        if override
        else Path(_platform_user_data_dir(APP_DATA_DIR_NAME, appauthor=False, roaming=True))
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_file() -> Path:
    return user_data_dir() / "settings.yaml"


def log_dir() -> Path:
    path = user_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
