import ctypes
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMessageBox

from src.common import APP_FULLNAME, ICON_PATH
from src.logger import info, warning, error


NOTICE_BODY = (
    "如不以管理员模式启动，将导致游戏过程中无法正常监听按键，"
    "需要切换至本软件窗口才可使用快捷键，导致体验不佳。"
)


def is_running_as_admin() -> bool:
    """检测当前进程是否以管理员（已提升权限）模式运行。"""
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as e:
        error(f"Failed to check admin privilege: {e}")
        return False


def relaunch_as_admin() -> bool:
    """
    尝试以管理员身份重新启动本程序。

    返回 True 表示已成功发起提权启动，调用方随后应退出当前实例；
    返回 False 表示启动失败（如用户取消了 UAC 授权）。
    """
    if sys.platform != "win32":
        return False

    try:
        SW_SHOWNORMAL = 1
        if getattr(sys, "frozen", False):
            # PyInstaller 打包环境：直接重启 exe 本身
            target = sys.executable
            params = None
        else:
            # 源码环境：用当前解释器重新运行入口脚本
            target = sys.executable
            params = f'"{sys.argv[0]}"'

        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", target, params, None, SW_SHOWNORMAL)
        if ret > 32:
            info("Relaunch as administrator requested successfully.")
            return True
        warning(f"ShellExecuteW('runas') failed with code {ret} (user may have declined UAC).")
        return False
    except Exception as e:
        error(f"Failed to relaunch as administrator: {e}")
        return False


def _make_box(icon: QMessageBox.Icon, title: str) -> QMessageBox:
    """创建带程序图标和标题的提示弹窗。"""
    box = QMessageBox()
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setWindowIcon(QIcon(ICON_PATH))
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    return box


def show_admin_prompt() -> bool:
    """
    启动时检测管理员权限并弹窗提示相关信息。

    - 已以管理员模式运行：弹出提示告知游戏内可正常监听按键（3 秒后自动关闭）。
    - 未以管理员模式运行：弹出警告说明按键监听的影响，
      并提供「以管理员身份重新启动」选项。

    返回 True 表示继续运行当前实例；
    返回 False 表示用户选择提权重启、当前实例应当退出。
    """
    if sys.platform != "win32":
        return True

    admin = is_running_as_admin()
    info(f"Running as administrator: {admin}")

    title = f"{APP_FULLNAME} - 管理员模式提示"

    if admin:
        box = _make_box(QMessageBox.Icon.Information, title)
        box.setText("当前已以【管理员模式】运行。")
        box.setInformativeText("游戏过程中可正常监听全局按键（快捷键），无需切换窗口。")
        # 该弹窗仅为状态告知，3 秒后自动关闭，无需手动点击
        auto_close_timer = QTimer()
        auto_close_timer.setSingleShot(True)
        auto_close_timer.timeout.connect(box.accept)
        auto_close_timer.start(3000)
        box.exec()
        auto_close_timer.stop()
        return True

    box = _make_box(QMessageBox.Icon.Warning, title)
    box.setText("当前未以【管理员模式】运行！")
    box.setInformativeText(
        NOTICE_BODY + "\n\n"
        "建议点击「以管理员身份重新启动」；也可以右键程序图标，"
        "选择「以管理员身份运行」后手动启动。"
    )
    btn_restart = box.addButton("以管理员身份重新启动", QMessageBox.ButtonRole.AcceptRole)
    btn_continue = box.addButton("继续运行", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(btn_continue)
    box.exec()

    if box.clickedButton() is btn_restart:
        info("User chose to relaunch as administrator.")
        if relaunch_as_admin():
            return False
        # 提权重启失败（如 UAC 授权被取消），提示后继续以普通模式运行
        warn = _make_box(QMessageBox.Icon.Warning, title)
        warn.setText("未能以管理员身份重新启动（可能取消了授权），将继续以普通模式运行。")
        warn.setInformativeText(NOTICE_BODY)
        warn.exec()
    else:
        info("User chose to continue without administrator privileges.")

    return True
