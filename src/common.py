from pathlib import Path
import os
from datetime import timedelta
from platformdirs import user_data_dir, user_desktop_dir
import yaml


APP_NAME = "nightreign-overlay-helper"
APP_NAME_CHS = "黑夜君临悬浮助手"
APP_VERSION = "0.8.3"
APP_FULLNAME = f"{APP_NAME_CHS}v{APP_VERSION}"
APP_AUTHOR = "NeuraXmy"

GAME_WINDOW_TITLE = "ELDEN RING NIGHTREIGN"


def get_asset_path(path: str) -> str:
    return str(Path("assets") / path)

def get_data_path(path: str) -> str:
    return str(Path("data") / path)

def get_appdata_path(filename: str) -> str:
    if appdata := os.getenv("APPDATA"):
        app_data_dir = Path(appdata) / APP_NAME
    else:
        app_data_dir = Path(user_data_dir(appname=APP_NAME, appauthor=APP_AUTHOR))
    app_data_dir.mkdir(parents=True, exist_ok=True)
    return str(app_data_dir / filename)

def get_desktop_path(filename: str = "") -> str:
    desktop = Path(user_desktop_dir())
    desktop.mkdir(exist_ok=True)
    return str(desktop / filename) if filename else str(desktop)


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
    

def load_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Failed to load YAML file {path}: {e}")
        return {}

def save_yaml(path: str, data: dict):
    # 保存到临时文件然后替换，防止写入过程中程序崩溃导致文件损坏
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"Failed to save YAML file {path}: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

