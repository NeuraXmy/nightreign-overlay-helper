import pygame
from PyQt6.QtCore import QObject, pyqtSignal
from pynput import keyboard
from PyQt6.QtWidgets import (QWidget, QPushButton, QVBoxLayout, QDialog, 
                             QLabel, QHBoxLayout)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from dataclasses import dataclass

from src.logger import info, warning, error


class InputWorker(QObject):
    key_combo_pressed = pyqtSignal(tuple)
    joystick_button_pressed = pyqtSignal(int)
    joystick_combo_pressed = pyqtSignal(tuple)
    joystick_axis_moved = pyqtSignal(tuple)
    joystick_hat_moved = pyqtSignal(tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self.joysticks = []

        self.current_pressed_keys = set()
        self.keyboard_listener = None 

        self.current_pressed_joystick_buttons = {}

    def _get_key_identifier(self, key):
        """一个健壮的方法，用于从 pynput 的 key 对象中获取可读的标识符。"""
        try:
            if key is None:
                return None
            # 处理特殊键 (Ctrl, Alt, Shift, F1, 等)
            if isinstance(key, keyboard.Key):
                # 返回按键名称，例如 'ctrl_l', 'esc'
                return key.name
            # 处理普通字符键
            if isinstance(key, keyboard.KeyCode):
                # key.char 可能是 None，或者是一个控制字符
                if key.char is None:
                    return None
                if ord(key.char) < 128:
                    char_ord = ord(key.char)
                    # 检查是否为 Ctrl+[a-z] 生成的控制字符 (ASCII 1-26)
                    if 1 <= char_ord <= 26:
                        # 将其转换回对应的字母 'a'-'z'
                        return chr(char_ord + 96) 
                    
                    # 如果是其他可打印字符，直接返回
                    return key.char
                else:
                    return None
            
            # 作为后备，返回按键的字符串表示
            return str(key)
        except Exception as e:
            error(f"Error in _get_key_identifier: {e}")
            return None

    def run(self):
        # --- Pygame 初始化 (Joystick Only) ---
        pygame.init()
        pygame.joystick.init()
        info("Pygame initialized in worker thread (Joystick Only).")
        clock = pygame.time.Clock()

        # --- pynput 键盘监听器初始化 ---
        info("pynput keyboard listener starting in worker thread.")
        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )
        self.keyboard_listener.start()

        while self._running:
            self._scan_joysticks()
            # 处理 Pygame 事件 (只处理手柄相关事件)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False
                    break

                # --- 手柄事件处理 ---
                elif event.type == pygame.JOYBUTTONDOWN:
                    joystick_id = event.joy
                    button_index = event.button
                    self.joystick_button_pressed.emit(button_index)

                    if joystick_id not in self.current_pressed_joystick_buttons:
                        self.current_pressed_joystick_buttons[joystick_id] = set()
                    self.current_pressed_joystick_buttons[joystick_id].add(button_index)
                    self.joystick_combo_pressed.emit(tuple(sorted(self.current_pressed_joystick_buttons[joystick_id])))

                elif event.type == pygame.JOYBUTTONUP:
                    joystick_id = event.joy
                    button_index = event.button
                    if joystick_id in self.current_pressed_joystick_buttons and \
                       button_index in self.current_pressed_joystick_buttons[joystick_id]:
                        self.current_pressed_joystick_buttons[joystick_id].remove(button_index)
                        # self.joystick_combo_pressed.emit(tuple(sorted(self.current_pressed_joystick_buttons[joystick_id])))
                       
                elif event.type == pygame.JOYAXISMOTION:
                    self.joystick_axis_moved.emit((event.joy, event.axis, event.value))

                elif event.type == pygame.JOYHATMOTION:
                    self.joystick_hat_moved.emit((event.joy, event.hat, event.value))

            clock.tick(10)

        info("Pygame worker thread finished.")
        if self.keyboard_listener and self.keyboard_listener.is_alive():
            self.keyboard_listener.stop()
            self.keyboard_listener.join()
            info("pynput keyboard listener stopped.")
        pygame.quit()

    def _on_key_press(self, key):
        try:
            key_identifier = self._get_key_identifier(key)
            if key_identifier and key_identifier not in self.current_pressed_keys:
                self.current_pressed_keys.add(key_identifier)
                self.key_combo_pressed.emit(tuple(sorted(self.current_pressed_keys)))
        except Exception as e:
            error(f"Error in _on_key_press: {e}")

    def _on_key_release(self, key):
        try:
            key_identifier = self._get_key_identifier(key)
            if key_identifier and key_identifier in self.current_pressed_keys:
                self.current_pressed_keys.remove(key_identifier)
                # self.key_combo_pressed.emit(tuple(sorted(self.current_pressed_keys)))
        except Exception as e:
            error(f"Error in _on_key_release: {e}")

    def _scan_joysticks(self):
        count = pygame.joystick.get_count()
        if count == len(self.joysticks):
            return
        self.joysticks = []
        for i in range(count):
            try:
                joystick = pygame.joystick.Joystick(i)
                joystick.init()
                self.joysticks.append(joystick)
                info(f"Detected Joystick {i}: {joystick.get_name()}")
            except pygame.error as e:
                error(f"Could not initialize joystick {i}: {e}")

    def stop(self):
        self._running = False


JOYSTICK_BUTTON_NAMES = {
    0: "B",
    1: "A",
    2: "Y",
    3: "X",
    4: "LB",
    5: "RB",
    6: "Select",
    7: "Start",
    8: "LStick",
    9: "RStick",
}

def format_combo(combo_type, combo_tuple):
    if combo_type == "keyboard":
        keys = []
        for k in combo_tuple:
            cleaned_key = k.replace('_l', '').replace('_r', '')
            keys.append(cleaned_key.upper())
        return "键盘 " + " + ".join(sorted(keys))
    elif combo_type == "joystick":
        buttons = [JOYSTICK_BUTTON_NAMES.get(b, f"Btn{b}") for b in combo_tuple]
        return "手柄 " + " + ".join(buttons)
    return "未设置"


class InputSettingDialog(QDialog):
    """
    一个对话框，用于捕获用户的键盘或手柄组合键输入。
    """
    def __init__(self, worker: InputWorker, parent=None):
        super().__init__(parent)
        self.worker = worker
        
        # 内部状态
        self.input_type = None  # 'keyboard', 'joystick', or None
        self.current_combo = ()
        
        # 最终要返回给主控件的设置
        self.final_setting = ('none', ())

        self.setWindowTitle("设置按键")
        self.setMinimumSize(400, 200)

        # --- UI 组件 ---
        self.layout: QHBoxLayout = QVBoxLayout(self)
        self.prompt_label = QLabel("请按下键盘或手柄组合键...\n(第一个按下的设备类型将被锁定)")
        self.prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.combo_display_label = QLabel("等待输入...")
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        self.combo_display_label.setFont(font)
        self.combo_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.combo_display_label.setStyleSheet("color: #3498db; border: 1px solid #ccc; padding: 10px;")

        self.clear_button = QPushButton("清空")
        self.cancel_button = QPushButton("取消")
        self.confirm_button = QPushButton("确认")

        # --- 布局 ---
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.clear_button)
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.confirm_button)

        self.layout.addWidget(self.prompt_label)
        self.layout.addWidget(self.combo_display_label)
        self.layout.addStretch()
        self.layout.addLayout(button_layout)

        # --- 信号和槽连接 ---
        self.confirm_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.clear_button.clicked.connect(self._clear_setting)
        
        self.worker.key_combo_pressed.connect(self._on_key_combo)
        self.worker.joystick_combo_pressed.connect(self._on_joystick_combo)

    def _on_key_combo(self, combo: tuple):
        # 如果已经锁定了手柄输入，则忽略键盘
        if self.input_type == 'joystick':
            return
        
        # 如果这是第一次输入，则锁定为键盘
        if not self.input_type:
            self.input_type = 'keyboard'

        self.current_combo = combo
        self._update_display()

    def _on_joystick_combo(self, combo: tuple):
        # 如果已经锁定了键盘输入，则忽略手柄
        if self.input_type == 'keyboard':
            return
            
        # 如果这是第一次输入，则锁定为手柄
        if not self.input_type:
            self.input_type = 'joystick'

        self.current_combo = combo
        self._update_display()
        
    def _update_display(self):
        if not self.current_combo:
            self.combo_display_label.setText("等待输入...")
            return
        
        display_text = format_combo(self.input_type, self.current_combo)
        self.combo_display_label.setText(display_text)

    def _clear_setting(self):
        """当点击清空按钮时调用"""
        self.final_setting = ('none', ())
        self.accept() # 关闭对话框并返回接受状态

    def accept(self):
        """重写 accept，在关闭前保存当前设置"""
        if self.input_type and self.current_combo:
            self.final_setting = (self.input_type, self.current_combo)
        super().accept()

    def get_setting(self):
        """供外部调用以获取最终设置"""
        return self.final_setting

    def closeEvent(self, event):
        """在关闭对话框时断开信号连接，防止内存泄漏"""
        self.worker.key_combo_pressed.disconnect(self._on_key_combo)
        self.worker.joystick_combo_pressed.disconnect(self._on_joystick_combo)
        super().closeEvent(event)



@dataclass
class InputSetting:
    type: str | None = None    # 'keyboard', 'joystick', or None
    combo: tuple | None = None

    @staticmethod
    def load_from_dict(data: dict) -> 'InputSetting':
        ret = InputSetting()
        if data is None:
            return ret
        ret.type = data.get('type')
        ret.combo = data.get('combo', tuple())
        if ret.combo is not None:
            ret.combo = tuple(ret.combo)
        return ret


class InputSettingWidget(QWidget):
    """
    一个封装了按键设置逻辑的控件。
    """
    # 当设置被确认后，发射此信号
    setting_changed = pyqtSignal(InputSetting)
    # 当设置的快捷键被触发时，发射此信号
    input_triggered = pyqtSignal()

    def __init__(self, worker: InputWorker, parent=None):
        super().__init__(parent)
        if not worker:
            raise ValueError("InputSettingWidget requires an InputWorker instance.")
        
        self.worker = worker
        self._setting_type = None # 'keyboard', 'joystick', or None
        self._setting_combo = ()

        # --- UI 组件 ---
        self.layout: QVBoxLayout = QVBoxLayout(self)
        self.layout.setContentsMargins(0,0,0,0)
        self.setting_button = QPushButton()
        # self.setting_button.setMinimumHeight(30)
        # self.setMinimumHeight(30)
        self.setting_button.setStyleSheet("padding: 4px;")
        self.layout.addWidget(self.setting_button)
        
        # --- 初始化 ---
        self._update_button_text()
        self.setting_button.clicked.connect(self._open_setting_dialog)
        self.worker.key_combo_pressed.connect(self.process_key_combo)
        self.worker.joystick_combo_pressed.connect(self.process_joystick_combo)
        
    def _update_button_text(self):
        """根据当前设置更新按钮上的文本"""
        text = format_combo(self._setting_type, self._setting_combo)
        self.setting_button.setText(text)

    def _open_setting_dialog(self):
        """打开设置对话框"""
        dialog = InputSettingDialog(self.worker, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._setting_type, self._setting_combo = dialog.get_setting()
            info(f"Setting confirmed: Type={self._setting_type}, Combo={self._setting_combo}")
            self._update_button_text()
            self.setting_changed.emit(InputSetting(self._setting_type, self._setting_combo))
        else:
            info("Setting canceled.")

    def set_setting(self, setting: InputSetting):
        """外部调用以设置当前控件的设置"""
        self._setting_type = setting.type
        self._setting_combo = setting.combo
        self._update_button_text()
        self.setting_changed.emit(setting)

    def get_setting(self) -> InputSetting:
        """获取当前控件保存的设置"""
        return InputSetting(self._setting_type, self._setting_combo)
    
    def process_key_combo(self, keys: tuple):
        if self._setting_type == 'keyboard' and keys == self._setting_combo:
            self.input_triggered.emit()
    
    def process_joystick_combo(self, buttons: tuple):
        if self._setting_type == 'joystick' and buttons == self._setting_combo:
            self.input_triggered.emit()
