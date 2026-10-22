"""Use the legacy journal location by default; isolated runs never touch it."""

import os
from pathlib import Path

from nightreign_overlay.core.paths import DATA_DIR_ENV, user_data_dir


def identity_directory() -> Path:
    if os.getenv(DATA_DIR_ENV) or not os.getenv("LOCALAPPDATA"):
        return user_data_dir() / "identity"
    return Path(os.environ["LOCALAPPDATA"]) / "NightreignOverlayHelper/identity"
