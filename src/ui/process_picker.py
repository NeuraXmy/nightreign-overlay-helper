"""手动选择截图进程的对话框。

默认按游戏窗口标题自动检测截图目标；PS5 串流等本机不存在游戏窗口的
场景，可在此选择提供游戏画面的进程（如串流软件），由设置页调用。
"""

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from src.logger import info, warning
from src.screencap.hwnd_resolver import list_capture_processes

AUTO_DETECT_LABEL = "自动检测（默认）"


class ProcessPickerDialog(QDialog):
    """列出当前带可见窗口的进程供选择，返回进程映像名（空串表示自动检测）。"""

    def __init__(self, parent=None, current: str = ""):
        super().__init__(parent)
        self.setWindowTitle("选择截图进程")
        self.resize(460, 520)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("选择提供游戏画面的窗口（例如 PS5 串流软件）："))

        self.list_widget = QListWidget()
        self._auto_item = QListWidgetItem(AUTO_DETECT_LABEL)
        self._auto_item.setData(0x0100, "")  # Qt.UserRole
        self.list_widget.addItem(self._auto_item)

        entries = list_capture_processes()
        if not entries:
            warning("ProcessPickerDialog: no selectable window processes found.")
        selected = None
        for title, exe in entries:
            item = QListWidgetItem(f"{title}    [{exe}]")
            item.setData(0x0100, exe)
            self.list_widget.addItem(item)
            if exe and exe.lower() == current.lower():
                selected = item
        self.list_widget.setCurrentItem(selected or self._auto_item)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_process(self) -> str:
        """返回选中的进程映像名；自动检测返回空串。"""
        item = self.list_widget.currentItem()
        return str(item.data(0x0100) or "") if item else ""


def pick_capture_process(parent=None, current: str = "") -> str | None:
    """弹出选择对话框；确认返回进程映像名（空串为自动检测），取消返回 None。"""
    dialog = ProcessPickerDialog(parent, current=current)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    process = dialog.selected_process()
    info(f"Capture process selected: {process or '(auto detect)'}")
    return process
