from PyQt6.QtWidgets import QWidget
from src.logger import info, warning


def set_widget_always_on_top(widget: QWidget):
    try:
        import win32gui
        import win32con

        hwnd = widget.winId().__int__()
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOPMOST,
            0,
            0,
            0,
            0,
            win32con.SWP_NOSIZE | win32con.SWP_NOMOVE,
        )
        info(f"Window HWND: {hwnd} set to TOPMOST.")
    except Exception as e:
        warning(f"Error setting system always on top: {e}")


def is_window_in_foreground(window_title: str) -> bool:
    """
    检查包含特定标题的窗口是否在 Windows 的最前面。
    """
    try:
        import win32gui

        active_window_handle = win32gui.GetForegroundWindow()
        active_window_title = win32gui.GetWindowText(active_window_handle)
        if window_title.lower() in active_window_title.lower():
            return True
        return False
    except Exception:
        return False
