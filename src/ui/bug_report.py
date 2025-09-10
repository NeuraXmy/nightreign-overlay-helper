import sys
import os
import zipfile
import io
import subprocess
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QLabel,
    QHBoxLayout,
)
from PyQt6.QtCore import Qt
from PIL import Image


class BugReportWindow(QMainWindow):
    def __init__(
        self,
        log_dir: str,
        export_dir: str,
        mail_address: str,
        max_screenshots: int = 5,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("BUG反馈")
        self.setGeometry(100, 100, 500, 400)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout: QVBoxLayout = QVBoxLayout(self.central_widget)

        self.feedback_label = QLabel("请详细描述您遇到的问题：")
        self.layout.addWidget(self.feedback_label)

        self.feedback_text = QTextEdit()
        self.layout.addWidget(self.feedback_text)

        self.screenshot_layout = QHBoxLayout()
        self.add_screenshot_button = QPushButton(f"添加截图 (最多{max_screenshots}张)")
        self.add_screenshot_button.clicked.connect(self.add_screenshots)
        self.screenshot_layout.addWidget(self.add_screenshot_button)
        self.screenshot_layout.addStretch()
        self.layout.addLayout(self.screenshot_layout)

        self.screenshot_label = QLabel("已选择的截图：")
        self.layout.addWidget(self.screenshot_label)

        self.screenshot_list_label = QLabel("")
        self.screenshot_list_label.setWordWrap(True)
        self.layout.addWidget(self.screenshot_list_label)

        self.submit_button = QPushButton("提交")
        self.submit_button.clicked.connect(self.submit_feedback)
        self.layout.addWidget(
            self.submit_button, alignment=Qt.AlignmentFlag.AlignCenter
        )

        self.selected_screenshots = []

        self.log_directory = log_dir
        self.export_directory = export_dir
        self.mail_address = mail_address
        self.max_screenshots = max_screenshots

    def add_screenshots(self):
        """打开文件对话框以选择截图"""
        if len(self.selected_screenshots) >= self.max_screenshots:
            QMessageBox.warning(
                self, "警告", f"您最多只能选择{self.max_screenshots}张截图。"
            )
            return

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择截图",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp)",
        )

        if files:
            remaining_slots = self.max_screenshots - len(self.selected_screenshots)
            if len(files) > remaining_slots:
                QMessageBox.warning(
                    self, "警告", f"您只能再添加 {remaining_slots} 张截图。"
                )
                files = files[:remaining_slots]
            self.selected_screenshots.extend(files)
            self.update_screenshot_list()

    def update_screenshot_list(self):
        """更新显示已选截图的标签"""
        if self.selected_screenshots:
            self.screenshot_list_label.setText("\n".join(self.selected_screenshots))
        else:
            self.screenshot_list_label.setText("")

    def submit_feedback(self):
        """提交反馈，打包文件"""
        feedback_content = self.feedback_text.toPlainText().strip()
        if not feedback_content:
            QMessageBox.warning(self, "警告", "请填写错误反馈内容。")
            return

        reply = QMessageBox.question(
            self,
            "确认导出",
            "您确定要导出此错误反馈吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.create_zip_package()
            self.close()

    def create_zip_package(self):
        """创建包含日志、反馈和截图的zip压缩包"""
        try:
            # 定义zip文件名和路径
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"Bug反馈{timestamp}_发送到{self.mail_address}.zip"
            os.makedirs(self.export_directory, exist_ok=True)
            zip_filepath = os.path.join(self.export_directory, zip_filename)

            with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
                # 1. 添加日志目录
                for root, _, files in os.walk(self.log_directory):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, self.log_directory)
                        zipf.write(file_path, arcname=os.path.join("logs", arcname))

                # 2. 添加错误反馈文本
                feedback_content = self.feedback_text.toPlainText()
                zipf.writestr(f"bug_report_{timestamp}.txt", feedback_content)

                # 3. 添加截图（转换为JPG）
                for i, filepath in enumerate(self.selected_screenshots):
                    try:
                        with Image.open(filepath) as img:
                            # 转换为RGB以保存为JPG
                            if img.mode in ("RGBA", "P"):
                                img = img.convert("RGB")

                            # 在内存中保存为JPG
                            jpg_buffer = io.BytesIO()
                            img.save(jpg_buffer, format="JPEG", quality=85)
                            jpg_buffer.seek(0)

                            # 写入zip文件
                            zipf.writestr(
                                f"screenshot_{i + 1}.jpg", jpg_buffer.getvalue()
                            )
                    except Exception as e:
                        print(f"无法处理截图 {filepath}: {e}")

            # 提示用户发送邮件
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("导出成功")
            msg_box.setText(
                f"即将自动打开文件位置\n"
                f"请将导出后的文件通过邮件发送到 {self.mail_address}\n"
                f"邮箱无法发送zip文件可修改后缀为txt"
            )
            # 关键代码：设置文本可由鼠标选择
            msg_box.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            msg_box.exec()

            # 打开zip文件所在位置
            self.open_file_location(zip_filepath)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"创建压缩包时发生错误：\n{e}")

    def open_file_location(self, filepath):
        """在Windows文件资源管理器中打开并选中文件"""
        if sys.platform == "win32":
            filepath = os.path.abspath(filepath)
            subprocess.Popen(f'explorer /select,"{filepath}"')


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BugReportWindow(
        log_dir="sandbox/test",
        export_dir="sandbox/export",
        mail_address="test@example.com",
    )
    window.show()
    sys.exit(app.exec())
