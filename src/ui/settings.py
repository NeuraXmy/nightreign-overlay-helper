from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QSlider, QGroupBox, QCheckBox, QPushButton,
    QMessageBox, QApplication, QFrame, QComboBox,
)
from PyQt6.QtGui import QPixmap, QIcon
import yaml
from dataclasses import dataclass, asdict
import os
import ctypes

from src.updater import Updater
from src.common import (
    APP_FULLNAME, APP_NAME, APP_VERSION,
    get_appdata_path, get_asset_path, get_desktop_path,
    ICON_PATH, load_yaml, save_yaml,
)
from src.logger import info, warning, error, set_log_level, INFO, DEBUG
from src.config import Config
from src.ui.overlay import OverlayUIState, OverlayWidget
from src.ui.map_overlay import MapOverlayWidget, MapOverlayUIState
from src.ui.input import InputWorker, InputSettingWidget, InputSetting
from src.ui.capture_region import CaptureRegionWindow
from src.detector.rain_detector import RainDetector
from src.detector.utils import hls_to_rgb
from src.ui.bug_report import BugReportWindow
from src.ui.utils import process_region_to_adapt_scale, get_qt_screen_by_mss_region


BUTTON_STYLE = "padding: 4px; min-height: 20px;"

SETTINGS_SAVE_PATH = get_appdata_path("settings.yaml")
DETECT_REGION_TUTORIAL_IMG_PATH = get_asset_path("detect_region_tutorial/{i}.jpg")
COLOR_ALIGN_TUTORIAL_IMG_PATH = get_asset_path("color_align_tutorial/{i}.jpg")
MAP_DETECT_TUTORIAL_IMG_PATH = get_asset_path("map_detect_tutorial/{i}.jpg")
HP_DETECT_TUTORIAL_IMG_PATH = get_asset_path("hp_detect_tutorial/{i}.jpg")
ART_DETECT_TUTORIAL_IMG_PATH = get_asset_path("art_detect_tutorial/{i}.jpg")


class SettingsWindow(QWidget):
    update_overlay_ui_state_signal = pyqtSignal(OverlayUIState)
    update_map_overlay_ui_state_signal = pyqtSignal(MapOverlayUIState)

    def __init__(self, overlay: OverlayWidget, map_overlay: MapOverlayWidget, updater: Updater, input: InputWorker):
        super().__init__()
        config = Config.get()
        self.overlay = overlay
        self.map_overlay = map_overlay
        self.update_overlay_ui_state_signal.connect(overlay.update_ui_state)
        self.update_map_overlay_ui_state_signal.connect(map_overlay.update_ui_state)
        self.updater = updater
        self.input = input

        self.setWindowIcon(QIcon(ICON_PATH))
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f'{APP_NAME}.{APP_VERSION}')
        except Exception as e:
            warning(f"Failed to set AppUserModelID: {e}")

        self.setWindowTitle(f"{APP_FULLNAME} - 设置")
        self.setMinimumSize(350, 200)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        # 外观设置
        self.appearance_group = QGroupBox("计时器外观")
        self.appearance_layout = QVBoxLayout(self.appearance_group)

        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("大小"))
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(5, 1000)
        self.size_slider.setValue(self.overlay.width())
        self.size_slider.valueChanged.connect(self.update_overlay_size)
        size_layout.addWidget(self.size_slider)
        self.appearance_layout.addLayout(size_layout)
        
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("透明度"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(int(self.overlay.windowOpacity() * 100))
        self.opacity_slider.valueChanged.connect(self.update_overlay_opacity)
        opacity_layout.addWidget(self.opacity_slider)
        self.appearance_layout.addLayout(opacity_layout)

        set_position_center_layout = QHBoxLayout()
        set_position_center_button = QPushButton("设置水平居中")
        set_position_center_button.setStyleSheet(BUTTON_STYLE)
        set_position_center_button.clicked.connect(self.update_overlay_position_center)
        set_position_center_layout.addWidget(set_position_center_button)
        self.appearance_layout.addLayout(set_position_center_layout)

        reset_position_layout = QHBoxLayout()
        reset_position_button = QPushButton("重置位置到主屏幕中心")
        reset_position_button.setStyleSheet(BUTTON_STYLE)
        reset_position_button.clicked.connect(self.reset_overlay_position)
        reset_position_layout.addWidget(reset_position_button)
        self.appearance_layout.addLayout(reset_position_layout)

        hide_text_layout = QHBoxLayout()
        self.hide_text_checkbox = QCheckBox("隐藏文字")
        self.hide_text_checkbox.stateChanged.connect(self.update_hide_text)
        hide_text_layout.addWidget(self.hide_text_checkbox)
        self.appearance_layout.addLayout(hide_text_layout)

        self.appearance_layout.addWidget(QLabel("提示：现在可以用鼠标左键拖动调整位置"))
        self.appearance_layout.addWidget(QLabel("⚠️请使用窗口化/无边框窗口化模式启动游戏"))
        self.appearance_layout.addWidget(QLabel("⚠️悬浮窗与部分AI补帧工具（小黄鸭）不兼容\n"
                                                 "同时使用可能出现卡顿"))
                                                
        # 输入设置
        self.input_group = QGroupBox("计时快捷键")
        self.input_layout = QVBoxLayout(self.input_group)

        day_input_layout = QHBoxLayout()
        day_input_layout.addWidget(QLabel("重置缩圈"))
        self.day_input_setting_widget = InputSettingWidget(self.input)
        self.day_input_setting_widget.input_triggered.connect(self.updater.start_day_by_shortcut)
        day_input_layout.addWidget(self.day_input_setting_widget)
        self.input_layout.addLayout(day_input_layout)

        forward_day_input_layout = QHBoxLayout()
        forward_day_input_layout.addWidget(QLabel(f"快进缩圈{config.foward_day_seconds}秒"))
        self.forward_day_input_setting_widget = InputSettingWidget(self.input)
        self.forward_day_input_setting_widget.input_triggered.connect(self.updater.foward_day_by_shortcut)
        forward_day_input_layout.addWidget(self.forward_day_input_setting_widget)
        self.input_layout.addLayout(forward_day_input_layout)

        back_day_input_layout = QHBoxLayout()
        back_day_input_layout.addWidget(QLabel(f"倒退缩圈{config.back_day_seconds}秒"))
        self.back_day_input_setting_widget = InputSettingWidget(self.input)
        self.back_day_input_setting_widget.input_triggered.connect(self.updater.back_day_by_shortcut)
        back_day_input_layout.addWidget(self.back_day_input_setting_widget)
        self.input_layout.addLayout(back_day_input_layout)

        in_rain_input_layout = QHBoxLayout()
        in_rain_input_layout.addWidget(QLabel("开始雨中冒险"))
        self.in_rain_input_setting_widget = InputSettingWidget(self.input)
        self.in_rain_input_setting_widget.input_triggered.connect(self.updater.start_in_rain_by_shortcut)
        in_rain_input_layout.addWidget(self.in_rain_input_setting_widget)
        self.input_layout.addLayout(in_rain_input_layout)

        self.input_layout.addWidget(QLabel("点击按钮修改，支持键盘或手柄组合键"))


        # 性能设置
        self.performance_group = QGroupBox("性能")
        self.performance_layout = QVBoxLayout(self.performance_group)

        detect_interval_layout = QHBoxLayout()
        detect_interval_layout.addWidget(QLabel("自动检测频率"))
        self.detect_interval_combobox = QComboBox()
        for k in config.detect_intervals.keys():
            self.detect_interval_combobox.addItem(k)
        self.detect_interval_combobox.setCurrentText("高")
        self.detect_interval_combobox.currentTextChanged.connect(self.update_detect_interval)
        detect_interval_layout.addWidget(self.detect_interval_combobox)
        self.performance_layout.addLayout(detect_interval_layout)

        only_show_when_game_foreground_layout = QHBoxLayout()
        self.only_show_when_game_foreground_checkbox = QCheckBox("仅在游戏时显示和检测")
        self.only_show_when_game_foreground_checkbox.setChecked(False)
        self.only_show_when_game_foreground_checkbox.stateChanged.connect(self.update_only_show_when_game_foreground)
        only_show_when_game_foreground_layout.addWidget(self.only_show_when_game_foreground_checkbox)
        self.performance_layout.addLayout(only_show_when_game_foreground_layout)

        self.performance_layout.addWidget(QLabel("⚠️开启HDR（显示设置->高动态范围成像）\n可能导致检测失效"))

        # 自动计时设置
        self.auto_timer_group = QGroupBox("缩圈&雨中冒险倒计时")
        self.auto_timer_layout = QVBoxLayout(self.auto_timer_group)

        screenshot_region_help_layout = QHBoxLayout()
        help_button = QPushButton("查看自动计时帮助")
        help_button.setStyleSheet("padding: 6px;")
        help_button.clicked.connect(self.show_capture_day1_hpcolor_region_tutorial)
        screenshot_region_help_layout.addWidget(help_button)
        self.auto_timer_layout.addLayout(screenshot_region_help_layout)

        auto_timer_enable_layout = QHBoxLayout()
        dayx_detect_enable_layout = QHBoxLayout()
        self.dayx_detect_enable_checkbox = QCheckBox("缩圈自动计时")
        self.dayx_detect_enable_checkbox.stateChanged.connect(self.update_dayx_detect_enable)
        dayx_detect_enable_layout.addWidget(self.dayx_detect_enable_checkbox)
        dayx_detect_enable_layout.addStretch()
        auto_timer_enable_layout.addLayout(dayx_detect_enable_layout)
        in_rain_detect_enable_layout = QHBoxLayout()
        self.in_rain_detect_enable_checkbox = QCheckBox("雨中冒险自动计时")
        self.in_rain_detect_enable_checkbox.stateChanged.connect(self.update_in_rain_detect_enable)
        in_rain_detect_enable_layout.addWidget(self.in_rain_detect_enable_checkbox)
        in_rain_detect_enable_layout.addStretch()
        auto_timer_enable_layout.addLayout(in_rain_detect_enable_layout)
        self.auto_timer_layout.addLayout(auto_timer_enable_layout)

        screenshot_region_layout = QHBoxLayout()
        screenshot_region_layout.addWidget(QLabel("截取检测区域快捷键"))
        self.capture_dayx_hpcolor_region_input_widget = InputSettingWidget(self.input)
        self.capture_dayx_hpcolor_region_input_widget.input_triggered.connect(self.capture_day1_hpcolor_region)
        screenshot_region_layout.addWidget(self.capture_dayx_hpcolor_region_input_widget)
        self.auto_timer_layout.addLayout(screenshot_region_layout)

        self.dayx_detect_lang = "chs"
        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("游戏语言"))
        self.lang_combobox = QComboBox()
        self.lang_combobox.addItems(config.dayx_detect_langs.values())
        self.lang_combobox.setCurrentText(config.dayx_detect_langs[self.dayx_detect_lang])
        self.lang_combobox.currentTextChanged.connect(self.update_detect_lang)
        lang_layout.addWidget(self.lang_combobox)
        self.auto_timer_layout.addLayout(lang_layout)

        self.day1_detect_region = None
        self.day1_detect_region_label = QLabel("缩圈检测区域：未设置")
        self.auto_timer_layout.addWidget(self.day1_detect_region_label)

        self.hpcolor_detect_region = None
        self.hpcolor_detect_region_label = QLabel("雨中冒险检测区域：未设置")
        self.auto_timer_layout.addWidget(self.hpcolor_detect_region_label)

        hp_color_help_layout = QHBoxLayout()
        hp_color_help_button = QPushButton("查看校准血条颜色帮助")
        hp_color_help_button.setStyleSheet(BUTTON_STYLE)
        hp_color_help_button.clicked.connect(self.show_capture_hp_color_help)
        hp_color_help_layout.addWidget(hp_color_help_button)
        self.auto_timer_layout.addLayout(hp_color_help_layout)

        align_to_detect_hp_color_layout = QHBoxLayout()
        align_to_detect_hp_color_layout.addWidget(QLabel("校准血条颜色快捷键"))
        self.align_to_detect_hp_color_input_widget = InputSettingWidget(self.input)
        self.align_to_detect_hp_color_input_widget.input_triggered.connect(self.capture_hp_color)
        align_to_detect_hp_color_layout.addWidget(self.align_to_detect_hp_color_input_widget)
        self.auto_timer_layout.addLayout(align_to_detect_hp_color_layout)
        
        self.not_in_rain_hls = None
        self.in_rain_hls = None
        hp_color_layout = QHBoxLayout()
        hp_color_layout.addWidget(QLabel("正常血条颜色:"))
        self.not_in_rain_label = QLabel("默认")
        hp_color_layout.addWidget(self.not_in_rain_label)
        hp_color_layout.addStretch()
        hp_color_layout.addWidget(QLabel("雨中血条颜色:"))
        self.in_rain_label = QLabel("默认")
        hp_color_layout.addWidget(self.in_rain_label)
        self.auto_timer_layout.addLayout(hp_color_layout)

        clear_to_detect_hp_layout = QHBoxLayout()
        clear_to_detect_hp_color = QPushButton("重置血条颜色设置")
        clear_to_detect_hp_color.setStyleSheet("padding: 6px;")
        clear_to_detect_hp_color.clicked.connect(self.clear_hp_color)
        clear_to_detect_hp_layout.addWidget(clear_to_detect_hp_color)
        clear_to_detect_hp_layout.addStretch()
        self.auto_timer_layout.addLayout(clear_to_detect_hp_layout)

        # 地图识别设置
        self.map_detect_group = QGroupBox("地图识别")
        self.map_detect_layout = QVBoxLayout(self.map_detect_group)

        map_detect_help_layout = QHBoxLayout()
        map_help_button = QPushButton("查看地图识别帮助")
        map_help_button.setStyleSheet(BUTTON_STYLE)
        map_help_button.clicked.connect(self.show_capture_map_region_tutorial)
        map_detect_help_layout.addWidget(map_help_button)
        self.map_detect_layout.addLayout(map_detect_help_layout)

        map_detect_enable_layout = QHBoxLayout()
        self.map_detect_enable_checkbox = QCheckBox("启用地图识别")
        self.map_detect_enable_checkbox.stateChanged.connect(self.update_map_detect_enable)
        map_detect_enable_layout.addWidget(self.map_detect_enable_checkbox)
        map_detect_enable_layout.addStretch()
        self.map_detect_layout.addLayout(map_detect_enable_layout)

        capture_map_region_input_setting_layout = QHBoxLayout()
        capture_map_region_input_setting_layout.addWidget(QLabel("截取地图区域快捷键"))
        self.capture_map_region_input_widget = InputSettingWidget(self.input)
        self.capture_map_region_input_widget.input_triggered.connect(self.capture_map_region)
        capture_map_region_input_setting_layout.addWidget(self.capture_map_region_input_widget)
        self.map_detect_layout.addLayout(capture_map_region_input_setting_layout)

        self.map_region = None
        self.map_region_label = QLabel("当前地图区域: 未设置")
        self.map_detect_layout.addWidget(self.map_region_label)

        set_to_detect_map_input_setting_layout = QHBoxLayout()
        set_to_detect_map_input_setting_layout.addWidget(QLabel("识别地图快捷键"))
        self.set_to_detect_map_input_setting_widget = InputSettingWidget(self.input)
        self.set_to_detect_map_input_setting_widget.input_triggered.connect(self.updater.set_to_detect_map_pattern_once)
        set_to_detect_map_input_setting_layout.addWidget(self.set_to_detect_map_input_setting_widget)
        self.map_detect_layout.addLayout(set_to_detect_map_input_setting_layout)

        show_map_overlay_input_setting_layout = QHBoxLayout()
        show_map_overlay_input_setting_layout.addWidget(QLabel("显示/隐藏信息快捷键"))
        self.show_map_overlay_input_setting_widget = InputSettingWidget(self.input)
        self.show_map_overlay_input_setting_widget.input_triggered.connect(updater.show_or_hide_map_overlay_by_shortcut)
        show_map_overlay_input_setting_layout.addWidget(self.show_map_overlay_input_setting_widget)
        self.map_detect_layout.addLayout(show_map_overlay_input_setting_layout)

        # 其他设置
        self.other_group = QGroupBox("其他")
        self.other_layout = QVBoxLayout(self.other_group)

        debug_layout = QHBoxLayout()
        self.other_layout.addLayout(debug_layout)

        bug_report_button = QPushButton("BUG反馈")
        bug_report_button.setStyleSheet(BUTTON_STYLE)
        bug_report_button.clicked.connect(self.open_bug_report_window)
        debug_layout.addWidget(bug_report_button)

        debug_log_layout = QHBoxLayout()
        self.debug_log_checkbox = QCheckBox("开启调试日志")
        self.debug_log_checkbox.setChecked(False)
        self.debug_log_checkbox.stateChanged.connect(self.update_debug_log)
        debug_log_layout.addWidget(self.debug_log_checkbox)
        debug_layout.addLayout(debug_log_layout)

        # HDR图像处理选项
        hdr_processing_layout = QHBoxLayout()
        self.hdr_processing_checkbox = QCheckBox("启用HDR图像处理")
        self.hdr_processing_checkbox.setChecked(True)
        self.hdr_processing_checkbox.setToolTip(
            "在HDR显示模式下启用此选项可提高识别准确性\n"
            "程序会自动对不同检测模块应用最佳的图像处理方式：\n"
            "• 缩圈倒计时：HDR到SDR转换\n"
            "• 地图识别：图像归一化(CLAHE)\n"
            "• 血条/雨中检测：保持原始图像\n"
            "如果遇到识别问题，可以尝试关闭此选项"
        )
        self.hdr_processing_checkbox.stateChanged.connect(self.update_hdr_processing)
        hdr_processing_layout.addWidget(self.hdr_processing_checkbox)
        self.other_layout.addLayout(hdr_processing_layout)

        open_log_and_abouts_layout = QHBoxLayout()
        self.other_layout.addLayout(open_log_and_abouts_layout)

        open_log_button = QPushButton("打开日志位置")
        open_log_button.setStyleSheet(BUTTON_STYLE)
        open_log_button.clicked.connect(self.open_log_directory)
        open_log_and_abouts_layout.addWidget(open_log_button)

        abouts_button = QPushButton("关于")
        abouts_button.setStyleSheet(BUTTON_STYLE)
        abouts_button.clicked.connect(self.open_about_dialog)
        open_log_and_abouts_layout.addWidget(abouts_button)

        # HP检测设置
        self.hp_detect_group = QGroupBox("血条比例标记")
        self.hp_detect_layout = QVBoxLayout(self.hp_detect_group)
        
        hp_detect_help_layout = QHBoxLayout()
        hp_help_button = QPushButton("查看血条比例标记帮助")
        hp_help_button.setStyleSheet(BUTTON_STYLE)
        hp_help_button.clicked.connect(self.show_capture_hpbar_region_tutorial)
        hp_detect_help_layout.addWidget(hp_help_button)
        self.hp_detect_layout.addLayout(hp_detect_help_layout)

        hp_detect_enable_layout = QHBoxLayout()
        self.hp_detect_enable_checkbox = QCheckBox("启用血条比例标记")
        self.hp_detect_enable_checkbox.stateChanged.connect(self.update_hp_detect_enable)
        hp_detect_enable_layout.addWidget(self.hp_detect_enable_checkbox)
        hp_detect_enable_layout.addStretch()
        self.hp_detect_layout.addLayout(hp_detect_enable_layout)

        self.hpbar_region = None
        capture_hpbar_region_input_setting_layout = QHBoxLayout()
        capture_hpbar_region_input_setting_layout.addWidget(QLabel("截取血条区域快捷键"))
        self.capture_hpbar_region_input_widget = InputSettingWidget(self.input)
        self.capture_hpbar_region_input_widget.input_triggered.connect(self.capture_hpbar_region)
        capture_hpbar_region_input_setting_layout.addWidget(self.capture_hpbar_region_input_widget)
        self.hp_detect_layout.addLayout(capture_hpbar_region_input_setting_layout)

        self.hpbar_region_label = QLabel("当前血条区域: 未设置")
        self.hp_detect_layout.addWidget(self.hpbar_region_label)

        # 绝招计时器设置
        self.art_timer_group = QGroupBox("绝招倒计时")
        self.art_timer_layout = QVBoxLayout(self.art_timer_group)

        art_detect_help_layout = QHBoxLayout()
        art_help_button = QPushButton("查看绝招倒计时帮助")
        art_help_button.setStyleSheet(BUTTON_STYLE)
        art_help_button.clicked.connect(self.show_capture_art_region_tutorial)
        art_detect_help_layout.addWidget(art_help_button)
        self.art_timer_layout.addLayout(art_detect_help_layout)

        art_detect_enable_layout = QHBoxLayout()
        self.art_detect_enable_checkbox = QCheckBox("启用绝招倒计时")
        self.art_detect_enable_checkbox.stateChanged.connect(self.update_art_detect_enable)
        art_detect_enable_layout.addWidget(self.art_detect_enable_checkbox)
        art_detect_enable_layout.addStretch()
        self.art_timer_layout.addLayout(art_detect_enable_layout)

        self.art_region = None
        capture_art_region_input_setting_layout = QHBoxLayout()
        capture_art_region_input_setting_layout.addWidget(QLabel("截取绝招图标区域快捷键"))
        self.capture_art_region_input_widget = InputSettingWidget(self.input)
        self.capture_art_region_input_widget.input_triggered.connect(self.capture_art_region)
        capture_art_region_input_setting_layout.addWidget(self.capture_art_region_input_widget)
        self.art_timer_layout.addLayout(capture_art_region_input_setting_layout)

        use_art_input_setting_layout = QHBoxLayout()
        use_art_input_setting_layout.addWidget(QLabel("绝招快捷键"))
        self.use_art_input_setting_widget = InputSettingWidget(self.input)
        self.use_art_input_setting_widget.input_triggered.connect(self.updater.use_art_by_shortcut)
        use_art_input_setting_layout.addWidget(self.use_art_input_setting_widget)
        self.art_timer_layout.addLayout(use_art_input_setting_layout)

        self.art_region_label = QLabel("当前绝招图标区域: 未设置")
        self.art_timer_layout.addWidget(self.art_region_label)

        # Layouts  
        layouts = [QVBoxLayout() for _ in range(3)]

        layouts[0].addWidget(self.appearance_group)
        layouts[0].addWidget(self.input_group)

        layouts[1].addWidget(self.performance_group)
        layouts[1].addWidget(self.auto_timer_group)
        layouts[1].addWidget(self.other_group)

        layouts[2].addWidget(self.map_detect_group)
        layouts[2].addWidget(self.hp_detect_group)
        layouts[2].addWidget(self.art_timer_group)

        self.layout: QHBoxLayout = QHBoxLayout(self)
        for l in layouts:
            l.addStretch()
            self.layout.addLayout(l)

        # 加载设置
        self.load_settings()


    def load_settings(self):
        try:
            def load_checkbox_state(checkbox: QCheckBox, state: bool):
                checkbox.setChecked(not state)
                checkbox.setChecked(state)
            def load_slider_value(slider: QSlider, value: int):
                slider.setValue(value - 1)
                slider.setValue(value)
            def load_combobox_value(combobox: QComboBox, value: str):
                combobox.setCurrentText(None)
                combobox.setCurrentText(value)

            info("------------------------")
            info("Start to load settings")
            config = Config.get()
            if os.path.exists(SETTINGS_SAVE_PATH):
                data = load_yaml(SETTINGS_SAVE_PATH)
                info(f"Loaded settings from {SETTINGS_SAVE_PATH}")
            else:
                data = {}
                warning(f"Settings file not found: {SETTINGS_SAVE_PATH}, using defaults")
            # 外观
            load_slider_value(self.size_slider, data.get("size", 200))
            load_slider_value(self.opacity_slider, data.get("opacity", 60))
            self.update_overlay_ui_state_signal.emit(OverlayUIState(
                x=data.get("x"),
                y=data.get("y"),
            ))
            load_checkbox_state(self.hide_text_checkbox, data.get("hide_text", False))
            # 快捷键
            self.day_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("day_input_setting")))
            self.forward_day_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("forward_day_input_setting")))
            self.back_day_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("back_day_input_setting")))
            self.in_rain_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("in_rain_input_setting")))
            # 性能
            load_checkbox_state(self.only_show_when_game_foreground_checkbox, data.get("only_show_when_game_foreground", False))
            load_combobox_value(self.detect_interval_combobox, data.get("detect_interval", "高"))
            # 自动计时
            load_checkbox_state(self.dayx_detect_enable_checkbox, data.get("dayx_detect_enabled", True))
            load_checkbox_state(self.in_rain_detect_enable_checkbox, data.get("in_rain_detect_enabled", True))
            self.capture_dayx_hpcolor_region_input_widget.set_setting(InputSetting.load_from_dict(data.get("capture_dayx_hpbar_region_input_setting")))
            self.dayx_detect_lang = data.get("dayx_detect_lang", "chs")
            load_combobox_value(self.lang_combobox, config.dayx_detect_langs[self.dayx_detect_lang])
            self.day1_detect_region = data.get("day1_detect_region", None)
            self.hpcolor_detect_region = data.get("hp_bar_detect_region", None)
            self.update_day1_hpcolor_regions()
            self.align_to_detect_hp_color_input_widget.set_setting(InputSetting.load_from_dict(data.get("align_to_detect_hp_color_input_setting")))
            self.not_in_rain_hls = data.get("not_in_rain_hls", None)
            self.in_rain_hls = data.get("in_rain_hls", None)
            self.update_hp_color()
            # 地图识别
            load_checkbox_state(self.map_detect_enable_checkbox, data.get("map_detect_enabled", True))
            self.capture_map_region_input_widget.set_setting(InputSetting.load_from_dict(data.get("capture_map_region_input_setting")))
            self.map_region = data.get("map_region", None)
            self.update_map_region()
            self.set_to_detect_map_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("set_to_detect_map_input_setting")))
            self.show_map_overlay_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("show_map_overlay_input_setting")))
            # 血条比例标记
            load_checkbox_state(self.hp_detect_enable_checkbox, data.get("hp_detect_enabled", True))
            self.capture_hpbar_region_input_widget.set_setting(InputSetting.load_from_dict(data.get("capture_hpbar_region_input_setting")))
            self.hpbar_region = data.get("hpbar_region", None)
            self.update_hpbar_region()
            # 绝招计时器
            load_checkbox_state(self.art_detect_enable_checkbox, data.get("art_detect_enabled", True))
            self.capture_art_region_input_widget.set_setting(InputSetting.load_from_dict(data.get("capture_art_region_input_setting")))
            self.use_art_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("use_art_input_setting")))
            self.art_region = data.get("art_region", None)
            self.update_art_region()
            # 其他
            load_checkbox_state(self.debug_log_checkbox, data.get("debug_log_enabled", False))
            # HDR图像处理选项 - 从settings.yaml读取
            load_checkbox_state(self.hdr_processing_checkbox, data.get("hdr_processing_enabled", True))

            info("Settings loaded successfully")
        except Exception as e:
            error(f"Failed to load settings: {e}")
        info("------------------------")

    def save_settings(self):
        try:
            data = {
                # 外观
                "size": self.size_slider.value(),
                "opacity": self.opacity_slider.value(),
                "x": self.overlay.x(),
                "y": self.overlay.y(),
                "hide_text": self.hide_text_checkbox.isChecked(),
                # 快捷键
                "day_input_setting": asdict(self.day_input_setting_widget.get_setting()),
                "forward_day_input_setting": asdict(self.forward_day_input_setting_widget.get_setting()),
                "back_day_input_setting": asdict(self.back_day_input_setting_widget.get_setting()),
                "in_rain_input_setting": asdict(self.in_rain_input_setting_widget.get_setting()),
                # 性能
                "only_show_when_game_foreground": self.only_show_when_game_foreground_checkbox.isChecked(),
                "detect_interval": self.detect_interval_combobox.currentText(),
                # 自动计时
                "dayx_detect_enabled": self.dayx_detect_enable_checkbox.isChecked(),
                "in_rain_detect_enabled": self.in_rain_detect_enable_checkbox.isChecked(),
                "capture_dayx_hpbar_region_input_setting": asdict(self.capture_dayx_hpcolor_region_input_widget.get_setting()),
                "dayx_detect_lang": self.dayx_detect_lang,
                "day1_detect_region": self.day1_detect_region,
                "hp_bar_detect_region": self.hpcolor_detect_region,
                "align_to_detect_hp_color_input_setting": asdict(self.align_to_detect_hp_color_input_widget.get_setting()),
                "not_in_rain_hls": self.not_in_rain_hls,
                "in_rain_hls": self.in_rain_hls,
                # 地图识别
                "map_detect_enabled": self.map_detect_enable_checkbox.isChecked(),
                "capture_map_region_input_setting": asdict(self.capture_map_region_input_widget.get_setting()),
                "map_region": self.map_region,
                "set_to_detect_map_input_setting": asdict(self.set_to_detect_map_input_setting_widget.get_setting()),
                "show_map_overlay_input_setting": asdict(self.show_map_overlay_input_setting_widget.get_setting()),
                # 血条比例标记
                "hp_detect_enabled": self.hp_detect_enable_checkbox.isChecked(),
                "capture_hpbar_region_input_setting": asdict(self.capture_hpbar_region_input_widget.get_setting()),
                "hpbar_region": self.hpbar_region,
                # 绝招计时器
                "art_detect_enabled": self.art_detect_enable_checkbox.isChecked(),
                "capture_art_region_input_setting": asdict(self.capture_art_region_input_widget.get_setting()),
                "use_art_input_setting": asdict(self.use_art_input_setting_widget.get_setting()),
                "art_region": self.art_region,
                # 其他
                "debug_log_enabled": self.debug_log_checkbox.isChecked(),
                "hdr_processing_enabled": self.hdr_processing_checkbox.isChecked(),
            }
            save_yaml(SETTINGS_SAVE_PATH, data)
            info(f"Saved settings to {SETTINGS_SAVE_PATH}")
        except Exception as e:
            error(f"Failed to save settings: {e}")


    def showEvent(self, event):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(
            draggable=True,
            is_setting_opened=True,
        ))
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
            is_setting_opened=True,
        ))
        self.updater.is_setting_opened = True
        # self.load_settings()
        super().showEvent(event)
        info("Settings window opened")

    def closeEvent(self, event):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(
            draggable=False,
            is_setting_opened=False,
        ))
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
            is_setting_opened=False,
        ))
        self.updater.is_setting_opened = False
        self.save_settings()
        super().closeEvent(event)
        info("Settings window closed")

    # =========================== Overlay Appearance =========================== #

    def update_overlay_size(self, value):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(scale=value / 100.0))
        info(f"Overlay size changed to {value}")

    def update_overlay_opacity(self, value):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(opacity=value / 100.0))
        info(f"Overlay opacity changed to {value}")

    def update_overlay_position_center(self):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(set_x_to_center=True))
        info("Overlay position set to center")

    def update_hide_text(self, state):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(hide_text=state))
        info(f"Overlay hide text set to {state}")

    def reset_overlay_position(self):
        screen_size = QApplication.primaryScreen().geometry().size()
        sw, sh = screen_size.width(), screen_size.height()
        ow, oh = self.overlay.width(), self.overlay.height()
        self.overlay.move(int((sw - ow) / 2), int((sh - oh) / 2))
        info("Overlay position reset to main screen center")

    # =========================== DayX In Rain Detect =========================== #

    def update_dayx_detect_enable(self, state):
        enabled = self.dayx_detect_enable_checkbox.isChecked()
        self.updater.dayx_detect_enabled = enabled
        info(f"DayX detect enabled: {enabled}")

    def update_detect_lang(self):
        config = Config.get()
        lang_name = self.lang_combobox.currentText()
        for k, v in config.dayx_detect_langs.items():
            if v == lang_name:
                self.dayx_detect_lang = k
                break
        self.updater.dayx_detect_lang = self.dayx_detect_lang
        info(f"DayX detect lang changed to {self.dayx_detect_lang}")

    def capture_day1_hpcolor_region(self):
        COLOR_HPCOLOR = "#a84747"
        COLOR_DAY_I = "#686435"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.8, 0.1), 'size': 32, 'color': COLOR_HPCOLOR, 'text': '点我并框出 血条 的区域'},
                {'pos': (0.8, 0.2), 'size': 32, 'color': COLOR_DAY_I, 'text': '点我并框出 DAY I 图标 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.8, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.8, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("Day1 hpcolor region setting canceled")
            return
        else:
            if screenshot := window.screenshot_at_saving:
                save_path = get_appdata_path("detect_region_screenshot.jpg")
                screenshot.save(save_path)
            for item in region_result:
                if item['color'] == COLOR_HPCOLOR:
                    self.hpcolor_detect_region = list(item['rect'])
                elif item['color'] == COLOR_DAY_I:
                    self.day1_detect_region = list(item['rect'])
            self.update_day1_hpcolor_regions()
            self.save_settings()

    def show_capture_day1_hpcolor_region_tutorial(self):
        tutorial_imgs = [QPixmap(str(DETECT_REGION_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 8)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("自动计时帮助")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("自动计时原理为通过定时截图分析画面内容，因此需要先框选检测区域，请按照以下步骤操作："))
        layout.addWidget(QLabel("1. 首先在设置界面调整\"截取检测区域快捷键\""))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("2. 开始一局单人游戏，在游戏第一天开始，出现\"DAY I\"图标时，按下设置的快捷键\n"
                                "画面会定格，并出现几个按钮（如果此时鼠标被锁定在屏幕中间，点一下左键即可）"))
        hlayout = QHBoxLayout()
        hlayout.addWidget(img_widgets[1])
        hlayout.addWidget(img_widgets[2])
        layout.addLayout(hlayout)
        layout.addWidget(QLabel("3. 点击\"点我并框出 血条 的区域\"按钮，然后用鼠标框选屏幕上的血条区域\n"
                                "框选的区域如下图所示，需要把血条的纯色内部框进去，尽量不要框到边框\n"
                                "⚠️即使你画面里的血条可能更长，但也只需要框【最左边的一小段】！"))
        layout.addWidget(img_widgets[3])
        layout.addWidget(QLabel("4. 点击\"点我并框出 DAY I 图标 的区域\"按钮，然后用鼠标框选屏幕上的 DAY I 图标\n"
                                "框选的区域如下图所示，需要把最左边的D和最右边的I的突出部分也要框进去\n"
                                "⚠️尽量严丝合缝，上下不要留有空隙"))
        layout.addWidget(img_widgets[4])
        layout.addWidget(QLabel("5. 最后点击\"保存\"按钮完成设置，在设置界面查看是否显示\"已设置\""))
        layout.addWidget(img_widgets[5])
        layout.addWidget(QLabel("6. 之后正常游玩即可自动计时，若修改游戏分辨率则需要重新框选"))
        layout.addWidget(QLabel("ℹ️ 缩圈自动计时可能失效的场景：DAY X图标出现时正在浏览背包和地图\n"
                                "ℹ️ 雨中冒险计时可能失效的场景：当前血量过少 / 开启HDR"))
        layout.addWidget(QLabel("⚠️ 即使开启了自动检测，仍然推荐设置快捷键作为备用"))
        layout.addWidget(QLabel("7. 如果缩圈检测失效，可能是因为游戏语言不同，可以调整设置里的\"游戏语言\""))
        layout.addWidget(img_widgets[6])
        layout.addWidget(QLabel("8. 如果雨中冒险检测失效，可能是因为色差，可以尝试设置里的\"校准血条颜色\""))
        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    
    def update_day1_hpcolor_regions(self):
        self.updater.day1_detect_region = self.day1_detect_region
        self.updater.hpcolor_detect_region = self.hpcolor_detect_region
        info(f"Updated detect regions: day1={self.day1_detect_region}, hpcolor={self.hpcolor_detect_region}")
        if self.day1_detect_region is None:
            self.day1_detect_region_label.setText("❌未设置缩圈检测区域")
        else:
            self.day1_detect_region_label.setText(f"✔️已设置缩圈检测区域: {self.day1_detect_region}")
        if self.hpcolor_detect_region is None:
            self.hpcolor_detect_region_label.setText("❌未设置雨中冒险检测区域")
        else:
            self.hpcolor_detect_region_label.setText(f"✔️已设置雨中冒险检测区域: {self.hpcolor_detect_region}")
 
    # ===========================  Hp Color Align =========================== #

    def update_in_rain_detect_enable(self, state):
        enabled = self.in_rain_detect_enable_checkbox.isChecked()
        self.updater.in_rain_detect_enabled = enabled
        info(f"In Rain detect enabled: {enabled}")

    def capture_hp_color(self):
        COLOR_NOT_IN_RAIN = "#b83232"
        COLOR_IN_RAIN = "#c03184"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.8, 0.1), 'size': 32, 'color': COLOR_NOT_IN_RAIN, 'text': '点我并框出 正常颜色血条 的区域'},
                {'pos': (0.8, 0.2), 'size': 32, 'color': COLOR_IN_RAIN,     'text': '点我并框出 雨中颜色血条 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.8, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.8, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("align hp color setting canceled")
            return
        else:
            for item in region_result:
                if item['color'] == COLOR_NOT_IN_RAIN:
                    self.not_in_rain_hls = RainDetector.get_to_detect_hp_hls(window.screenshot_pixmap, item['rect'])
                elif item['color'] == COLOR_IN_RAIN:
                    self.in_rain_hls = RainDetector.get_to_detect_hp_hls(window.screenshot_pixmap, item['rect'])
            self.update_hp_color()
            self.save_settings()

    def clear_hp_color(self):
        reply = QMessageBox.question(self, '确认', '确定要重置血条颜色设置为默认吗？', 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.not_in_rain_hls = None
            self.in_rain_hls = None
            self.update_hp_color()

    def show_capture_hp_color_help(self):
        tutorial_imgs = [QPixmap(str(COLOR_ALIGN_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 4)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("校准血条颜色帮助")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("ℹ️ 如果你设置完检测区域后能正常计时，则不需要进行校准"))
        layout.addWidget(QLabel("雨中冒险自动计时原理为检测血条颜色，有可能因为色差而失效，则需要使用校准步骤："))
        layout.addWidget(QLabel("1. 首先在设置界面调整\"校准血条颜色快捷键\""))
        layout.addWidget(QLabel("2. 开始一局单人游戏，在画面中有血条时按下设置的快捷键\n"
                                "画面定格并显示出按钮"))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("3. 如果画面中有正常血条，则点击\"点我框选 正常颜色血条 的区域\"按钮\n"
                                "然后拖动鼠标框出血条中的纯色部分，点击保存按钮"))
        layout.addWidget(img_widgets[1])
        layout.addWidget(QLabel("4. 以相同的步骤对在雨里的血条也框选一次（推荐单人去roll在圈外的出生点）"))
        layout.addWidget(QLabel("5. 设置界面看到两个颜色显示已设置即可，重置按钮可以退回到程序内置的默认颜色"))
        layout.addWidget(img_widgets[2])

        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def update_hp_color(self):
        self.updater.not_in_rain_hls = self.not_in_rain_hls
        self.updater.in_rain_hls = self.in_rain_hls
        info(f"Updated hp color: not_in_rain_hls={self.not_in_rain_hls}, in_rain_hls={self.in_rain_hls}")
        if self.not_in_rain_hls is None:
            self.not_in_rain_label.setText(f"默认")
            self.not_in_rain_label.setStyleSheet(f"background-color: #fff; color: black")
        else:
            self.not_in_rain_label.setText(f"已设置")
            self.not_in_rain_label.setStyleSheet(f"background-color: rgb{hls_to_rgb(self.not_in_rain_hls)}; color: white")
        if self.in_rain_hls is None:
            self.in_rain_label.setText(f"默认")
            self.in_rain_label.setStyleSheet(f"background-color: #fff; color: black")
        else:
            self.in_rain_label.setText(f"已设置")
            self.in_rain_label.setStyleSheet(f"background-color: rgb{hls_to_rgb(self.in_rain_hls)}; color: white")

    # =========================== Map Detect =========================== #

    def update_map_detect_enable(self, state):
        enabled = self.map_detect_enable_checkbox.isChecked()
        self.updater.map_detect_enabled = enabled
        info(f"Map detect enabled: {enabled}")

    def show_capture_map_region_tutorial(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("注意事项")
        msg.setText("""
该功能通过解包数据展示详细的地图剧透信息，建议在休闲游戏时避免使用。
请确保在不会影响到你以及你的队友的游戏体验的前提下使用该功能。
对于使用该功能对游戏体验产生的破坏，工具作者不承担任何责任。
（感谢来自 Fuwish@bilibili 的地图解包数据）
""".strip())
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

        tutorial_imgs = [QPixmap(str(MAP_DETECT_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 4)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("识别地图帮助")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("1. 首先在设置界面调整\"截取地图区域快捷键\""))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("2. 在任意有地图的游戏画面下按下设置的快捷键，并框选地图的区域\n"
                                "⚠️框的区域需要和地图的边框完全贴合"))
        layout.addWidget(img_widgets[1])
        layout.addWidget(QLabel("3. 回到设置界面看到\"已设置\"即可"))
        layout.addWidget(img_widgets[2])
        layout.addWidget(QLabel("4. 识别地图功能触发机制："))
        layout.addWidget(QLabel("ℹ️ 地图必须要完整展示（缩放到最小）时才能正常识别"))
        layout.addWidget(QLabel("ℹ️ 自动识别触发："))
        layout.addWidget(QLabel("       每次缩圈Day1计时开始后（无论是自动计时还是手动开始），第一次检测到完整地图时，\n"
                                "       会触发一次自动识别，直到下一次Day1计时开始前不会再次触发"))
        layout.addWidget(QLabel("ℹ️ 手动识别触发："))
        layout.addWidget(QLabel("       可以用“识别地图快捷键”手动触发识别"))
        layout.addWidget(QLabel("5. 识别成功后，地图在缩放到最小的状态时，信息会悬浮显示在地图上（暂时不支持跟随缩放）\n"
                                "可以用“显示/隐藏信息快捷键”切换显示\n"))
        layout.addWidget(QLabel("⚠️某些地图的数据可能有错误，发现错误可截图反馈给作者"))
        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def capture_map_region(self):
        COLOR_MAP_REGION = "#4384b9"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.5, 0.1), 'size': 32, 'color': COLOR_MAP_REGION, 'text': '点我并框出 地图 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.3, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.3, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("Map region setting canceled")
            return
        else:
            if screenshot := window.screenshot_at_saving:
                save_path = get_appdata_path("map_region_screenshot.jpg")
                screenshot.save(save_path)
            for item in region_result:
                if item['color'] == COLOR_MAP_REGION:
                    # 保持正方形
                    x, y, w, h = item['rect']
                    self.map_region = list((x, y, min(w, h), min(w, h)))
                self.update_map_region()
            self.save_settings()

    def update_map_region(self):
        map_region = self.map_region
        if map_region is not None:
            old_map_region = map_region.copy()
            screen = get_qt_screen_by_mss_region(map_region)
            scale = screen.devicePixelRatio()
            map_region = process_region_to_adapt_scale(map_region, scale)
            info(f"Map region adapted to screen scale {scale}: {old_map_region} -> {map_region}")
        if self.updater.map_region != map_region:
            self.updater.set_to_detect_map_pattern_once()
        self.updater.map_region = map_region
        info(f"Updated map region: map_region={map_region}")
        if map_region is None:
            self.map_region_label.setText("❌未设置地图区域")
        else:
            self.map_region_label.setText(f"✔️已设置地图区域: {map_region}")

    # =========================== Performance =========================== #

    def update_detect_interval(self, text: str):
        config = Config.get()
        detect_interval = config.detect_intervals.get(text, 0.2)
        self.updater.detect_interval = detect_interval
        info(f"Detect interval changed to {detect_interval} seconds ({text})")

    def update_only_show_when_game_foreground(self, state):
        enabled = self.only_show_when_game_foreground_checkbox.isChecked()
        self.update_overlay_ui_state_signal.emit(OverlayUIState(only_show_when_game_foreground=enabled))
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(only_show_when_game_foreground=enabled))
        self.updater.only_detect_when_game_foreground = enabled
        info(f"Overlay only show when game foreground: {enabled}")

    # =========================== HP Detect =========================== #
        
    def update_hp_detect_enable(self, state):
        self.updater.hp_detect_enabled = self.hp_detect_enable_checkbox.isChecked()
        info(f"HP detect enabled: {self.updater.hp_detect_enabled}")

    def capture_hpbar_region(self):
        COLOR_HPBAR_REGION = "#eb3b3b"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.5, 0.1), 'size': 32, 'color': COLOR_HPBAR_REGION, 'text': '点我并框出 血条 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.3, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.3, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("Hpbar region setting canceled")
            return
        else:
            if screenshot := window.screenshot_at_saving:
                save_path = get_appdata_path("hpbar_region_screenshot.jpg")
                screenshot.save(save_path)
            for item in region_result:
                if item['color'] == COLOR_HPBAR_REGION:
                    self.hpbar_region = list(item['rect'])
                self.update_hpbar_region()
            self.save_settings()

    def show_capture_hpbar_region_tutorial(self):
        tutorial_imgs = [QPixmap(str(HP_DETECT_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 5)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("血条比例标记")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("该功能用于在血条上显示：20%（血量偏低触发词条）\n"
                                "85%（非满血时触发的负面词条）和100%（满血）三个标记"))
        layout.addWidget(QLabel("1. 首先在设置界面调整\"截取血条区域快捷键\""))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("2. 在任意有血条的游戏画面下按下设置的快捷键，并框选血条的区域"))
        layout.addWidget(img_widgets[1])
        layout.addWidget(QLabel("⚠️ 框选的要求：\n"
                                "【高度】和血条完全相同\n"
                                "【左侧边】和血条贴合\n"
                                "【长度】无所谓"))
        layout.addWidget(img_widgets[2])
        layout.addWidget(QLabel("3. 回到设置界面看到\"已设置\"即可"))
        layout.addWidget(img_widgets[3])
        layout.addWidget(QLabel("4. 之后游玩时，在血条的上方就会悬浮显示三个标记\n"))
        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def update_hpbar_region(self):
        self.updater.hpbar_region = self.hpbar_region
        info(f"Updated hpbar region: hpbar_region={self.hpbar_region}")
        if self.hpbar_region is None:
            self.hpbar_region_label.setText("❌未设置血条区域")
        else:
            self.hpbar_region_label.setText(f"✔️已设置血条区域: {self.hpbar_region}")

    # =========================== Art Detect =========================== #

    def update_art_detect_enable(self, state):
        self.updater.art_detect_enabled = self.art_detect_enable_checkbox.isChecked()
        info(f"Art detect enabled: {self.updater.art_detect_enabled}")
    
    def capture_art_region(self):
        COLOR_ART_REGION = "#3235eb"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.5, 0.5), 'size': 32, 'color': COLOR_ART_REGION, 'text': '点我并框出 绝招图标 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.3, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.3, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("Art region setting canceled")
            return
        else:
            if screenshot := window.screenshot_at_saving:
                save_path = get_appdata_path("art_region_screenshot.jpg")
                screenshot.save(save_path)
            for item in region_result:
                if item['color'] == COLOR_ART_REGION:
                    self.art_region = list(item['rect'])
                self.update_art_region()
            self.save_settings()

    def show_capture_art_region_tutorial(self):
        tutorial_imgs = [QPixmap(str(ART_DETECT_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 6)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("绝招倒计时")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("该功能用于显示绝招效果的倒计时，支持的角色：女爵、隐士、执行者、复仇者、学者\n"
                                "只能显示自己使用的绝招效果的倒计时"))
        layout.addWidget(QLabel("1. 首先在设置界面调整\"截取绝招图标区域快捷键\""))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("2. 在任意有绝招图标的游戏画面下按下设置的快捷键，并框选绝招图标的区域"))
        layout.addWidget(img_widgets[1])
        layout.addWidget(QLabel("⚠️ 框选的要求：框和绝招图标的圆的边缘贴合"))
        layout.addWidget(img_widgets[2])
        layout.addWidget(QLabel("3. 回到设置界面看到\"已设置\""))
        layout.addWidget(img_widgets[3])
        layout.addWidget(QLabel("4. 然后设置\"绝招快捷键\"为你的游戏中使用绝招的按键即可"))
        layout.addWidget(img_widgets[4])
        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def update_art_region(self):
        self.updater.art_region = self.art_region
        info(f"Updated art region: art_region={self.art_region}")
        if self.art_region is None:
            self.art_region_label.setText("❌未设置绝招图标区域")
        else:
            self.art_region_label.setText(f"✔️已设置绝招图标区域: {self.art_region}")

    # =========================== Other =========================== #
    
    def open_log_directory(self):
        log_dir = get_appdata_path("")
        os.startfile(log_dir)

    def open_about_dialog(self):
        about_path = "manual.txt"
        with open(about_path, "r", encoding="utf-8") as f:
            about_text = f.read()
        msg = QMessageBox(self)
        msg.setWindowTitle("关于")
        msg.setText(about_text)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    
    def open_bug_report_window(self):
        w = BugReportWindow(
            log_dir=get_appdata_path(""),
            export_dir=get_desktop_path(),
            mail_address=Config.get().bug_report_email,
            parent=self,
        )
        w.show()

    def update_debug_log(self, state):
        enabled = self.debug_log_checkbox.isChecked()
        set_log_level(INFO if not enabled else DEBUG)
        info(f"Debug log enabled: {enabled}")

    def update_hdr_processing(self, state):
        enabled = self.hdr_processing_checkbox.isChecked()
        # 保存到updater，实时生效
        self.updater.hdr_processing_enabled = enabled
        info(f"HDR image processing enabled: {enabled}")

