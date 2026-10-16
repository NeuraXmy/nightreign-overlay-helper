"""Request Windows elevation before creating the application or claiming its instance key."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

from nightreign_overlay.meta import APP_NAME


def _shell_api():
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.IsUserAnAdmin.restype = wintypes.BOOL
    shell.ShellExecuteW.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_int,
    ]
    shell.ShellExecuteW.restype = ctypes.c_ssize_t
    return shell


def _show_failure(detail: str) -> None:
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    user.MessageBoxW.restype = ctypes.c_int
    user.MessageBoxW(
        None,
        "程序需要管理员权限，以启用联机延迟的 ETW 检测。\n"
        "管理员授权已取消或启动失败，程序未启动。请重新打开并允许授权，或选择“以管理员身份运行”。\n"
        f"{detail}",
        APP_NAME,
        0x10,
    )


def ensure_administrator() -> int | None:
    """Return None to continue, 0 after handing off, or 1 if elevation was refused/failed."""
    if sys.platform != "win32":
        return None
    try:
        shell = _shell_api()
        if shell.IsUserAnAdmin():
            return None
        # orig_argv preserves Python options and -m; frozen executables need only app arguments.
        arguments = sys.argv[1:] if getattr(sys, "frozen", False) else sys.orig_argv[1:]
        result = shell.ShellExecuteW(
            None, "runas", sys.executable, subprocess.list2cmdline(arguments), os.getcwd(), 1
        )
        if result > 32:
            return 0
        detail = f"Windows ShellExecute 错误码：{result}"
    except OSError as exc:
        detail = str(exc)
    _show_failure(detail)
    return 1
