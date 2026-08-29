import sys

from src.logger import warning


def find_game_hwnd(title: str) -> int | None:
    if sys.platform != "win32":
        warning(f"find_game_hwnd: non-Windows platform ({sys.platform}), returning None.")
        return None
    try:
        from src.screencap.maa_win32_screencap import find_window_by_title
        return find_window_by_title(title)
    except Exception as e:
        warning(f"find_game_hwnd: failed to find window by title '{title}': {e}")
        return None
