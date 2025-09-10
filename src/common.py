from pathlib import Path
import os
from datetime import timedelta

APP_NAME = "nightreign-overlay-helper"
APP_NAME_CHS = "黑夜君临悬浮助手"
APP_VERSION = "0.6.3"
APP_FULLNAME = f"{APP_NAME_CHS}v{APP_VERSION}"
APP_AUTHER = "NeuraXmy"

GAME_WINDOW_TITLE = "ELDEN RING NIGHTREIGN"


def get_asset_path(path: str) -> str:
    return str(Path("assets") / path)


def get_data_path(path: str) -> str:
    return str(Path("data") / path)


def _get_user_directory() -> Path:
    try:
        return Path.home()
    except Exception:
        try:
            return Path(os.path.expanduser("~"))
        except Exception:
            return Path(os.environ.get("USERPROFILE", os.environ.get("HOME", "C:\\")))


def get_desktop_path() -> str:
    try:
        user_dir = _get_user_directory()
        path = str(user_dir / "Desktop")
    except Exception:
        path = str(Path("C:\\") / "temp" / APP_NAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def get_appdata_path(path: str) -> str:
    try:
        appdata = os.environ.get("APPDATA")
        if appdata:
            path = str(Path(appdata) / APP_NAME / path)
        user_dir = _get_user_directory()
        path = str(user_dir / "AppData" / "Roaming" / APP_NAME / path)
    except Exception:
        path = str(Path("C:\\") / "temp" / APP_NAME / path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


ICON_PATH = get_asset_path("icon.ico")


def get_readable_timedelta(t: timedelta) -> str:
    seconds = int(t.total_seconds())
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}小时{minutes}分钟{seconds}秒"
    elif minutes > 0:
        return f"{minutes}分钟{seconds}秒"
    else:
        return f"{seconds}秒"
