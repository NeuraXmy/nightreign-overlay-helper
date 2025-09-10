import sys
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QAction, QCursor
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu
)

from src.ui.input import InputWorker
from src.ui.overlay import OverlayWidget
from src.ui.map_overlay import MapOverlayWidget
from src.ui.settings import SettingsWindow
from src.updater import Updater
from src.common import APP_FULLNAME, APP_VERSION, ICON_PATH
from src.logger import info, warning, error


def log_system_and_screen_info():
    try:
        import platform
        system = platform.system()
        release = platform.release()
        version = platform.version()
        info(f"Operating System: {system} {release} ({version})")
    except Exception as e:
        warning(f"Error getting OS info: {e}")

    try:
        import mss
        with mss.mss() as sct:
            monitors = sct.monitors
            info(f"MSS Detected {len(monitors)-1} monitor(s):")
            for i, monitor in enumerate(monitors[1:], start=1):
                info(f"    Monitor {i}: {monitor['width']}x{monitor['height']} at ({monitor['left']},{monitor['top']})")
    except Exception as e:
        warning(f"Error getting monitor info: {e}")

    try:
        from PyQt6.QtWidgets import QApplication
        app: QApplication = QApplication.instance()
        if app:
            screen = app.primaryScreen()
            size = screen.size()
            dpi = screen.logicalDotsPerInch()
            device_pixel_ratio = screen.devicePixelRatio()
            info(f"Primary Screen: {size.width()}x{size.height()}, DPI: {dpi}, Device Pixel Ratio: {device_pixel_ratio}")
    except Exception as e:
        warning(f"Error getting primary screen info: {e}")


if __name__ == "__main__":
    info("=" * 40)
    info(f"Starting app v{APP_VERSION}...")

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_Use96Dpi)
    app = QApplication(sys.argv)

    log_system_and_screen_info()
    
    # 防止因没有窗口而导致程序退出
    app.setQuitOnLastWindowClosed(False)

    # 创建对象
    input = InputWorker()
    overlay = OverlayWidget()
    map_overlay = MapOverlayWidget()
    updater = Updater(overlay, map_overlay)
    settings_window = SettingsWindow(overlay, map_overlay, updater, input)
    
    # 创建系统托盘图标和菜单
    tray_icon = QSystemTrayIcon()
    tray_icon.setIcon(QIcon(ICON_PATH))
    tray_icon.setToolTip(APP_FULLNAME)

    menu = QMenu()
    settings_action = QAction("设置")
    def show_settings():
        settings_window.show()
        settings_window.activateWindow()
        settings_window.raise_()
    settings_action.triggered.connect(show_settings)
    menu.addAction(settings_action)
    quit_action = QAction("退出")
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)
    menu.addSeparator()
    tray_icon.setContextMenu(menu)
    tray_icon.show()
    
    def show_menu_at_cursor_pos():
        cursor_pos = QCursor.pos()
        menu.move(cursor_pos)
        menu.show()
    def on_menu_show():
        overlay.is_menu_opened = True
        map_overlay.is_menu_opened = True
        # info("Menu opened")
    def on_menu_hide():
        overlay.is_menu_opened = False
        map_overlay.is_menu_opened = False
        # info("Menu closed")

    overlay.right_click_signal.connect(show_menu_at_cursor_pos)
    overlay.right_click_signal.connect(on_menu_show)
    menu.aboutToShow.connect(on_menu_show)
    menu.aboutToHide.connect(on_menu_hide)

    # 启动输入监听
    input_thread = QThread()
    input.moveToThread(input_thread)
    input_thread.started.connect(input.run)
    input_thread.start()
    
    # 设置并启动后台检测器
    updater_thread = QThread()
    updater.moveToThread(updater_thread)
    updater_thread.started.connect(updater.run)
    
    # 清理：程序退出时，停止worker并等待线程结束
    def on_quit():
        info("Stopping worker thread...")
        updater.stop()
        updater_thread.quit()
        updater_thread.wait()
        input.stop()
        input_thread.quit()
        input_thread.wait()
        info("Thread stopped. Exiting.")
    app.aboutToQuit.connect(on_quit)
    
    updater_thread.start()
    overlay.show()
    app.exec()

    info("App exited.")
    sys.exit(0)
