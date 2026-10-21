"""Application-wide constants."""

from __future__ import annotations

from nightreign_overlay import __version__

APP_ID = "nightreign-overlay-helper"
APP_NAME = "Nightreign Overlay Helper"
APP_AUTHOR = "NeuraXmy"
APP_VERSION = __version__
# Stable across versions and source/frozen entry points for Windows taskbar grouping.
WINDOWS_APP_USER_MODEL_ID = "NeuraXmy.NightreignOverlayHelper"

# Directory name used for user data; distinct from v1 so both versions can coexist.
APP_DATA_DIR_NAME = "NightreignOverlayHelper"

GAME_WINDOW_TITLE = "ELDEN RING NIGHTREIGN"

REPO_URL = "https://github.com/NeuraXmy/nightreign-overlay-helper"
GITHUB_REPO = "NeuraXmy/nightreign-overlay-helper"
GITEE_REPO = "NeuraXmy/nightreign-overlay-helper"
ISSUES_URL = f"{REPO_URL}/issues"
