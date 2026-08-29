import sys
from pathlib import Path


def get_native_dll_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "native"
    return Path(__file__).resolve().parent.parent.parent / "native"


def get_native_dll_path() -> Path:
    return get_native_dll_dir() / "MaaWin32Screencap.dll"
