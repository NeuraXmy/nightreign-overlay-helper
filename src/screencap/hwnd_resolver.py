import sys

from src.logger import warning


def find_game_hwnd(title: str, process_name: str | None = None) -> int | None:
    """解析目标窗口句柄。

    默认按窗口标题自动检测；指定 process_name（进程映像名，如
    RemotePlay.exe）时改为按进程查找其可见顶层窗口，供 PS5 串流等
    本机不存在游戏窗口的场景手动固定截图目标。
    """
    if sys.platform != "win32":
        warning(f"find_game_hwnd: non-Windows platform ({sys.platform}), returning None.")
        return None
    try:
        from src.screencap.maa_win32_screencap import find_hwnd_by_process, find_window_by_title
        if process_name:
            return find_hwnd_by_process(process_name)
        return find_window_by_title(title)
    except Exception as e:
        warning(f"find_game_hwnd: failed to find window (title '{title}'): {e}")
        return None


def list_capture_processes() -> list[tuple[str, str]]:
    """枚举可手动选择的截图进程，返回 (窗口标题, 进程映像名) 列表。"""
    if sys.platform != "win32":
        return []
    try:
        from src.screencap.maa_win32_screencap import list_window_processes
        return list_window_processes()
    except Exception as e:
        warning(f"list_capture_processes: failed to list window processes: {e}")
        return []
