from PyQt6.QtCore import QObject, pyqtSignal
import time
from enum import Enum
from PIL import Image

from src.common import GAME_WINDOW_TITLE
from src.config import Config
from src.logger import info, warning, error
from src.ui.input import InputWorker
from src.ui.overlay import OverlayWidget, OverlayUIState
from src.ui.map_overlay import MapOverlayWidget, MapOverlayUIState
from src.ui.hp_overlay import HpOverlayWidget, HpOverlayUIState
from src.detector import (
    DetectorManager, 
    DetectParam, 
    DayDetectParam,
    RainDetectParam,
    MapDetectParam,
    HpDetectParam,
    ArtDetectParam,
)
from src.detector.map_info import MapPattern
from src.ui.utils import is_window_in_foreground


class DoMatchMapPatternFlag(Enum):
    FALSE = 0
    PREPARE = 1
    TRUE = 2


class Phase(Enum):
    FIRST_CIRCLE_STABLE = 0
    FIRST_CIRCLE_SHRINK = 1
    SECOND_CIRCLE_STABLE = 2
    SECOND_CIRCLE_SHRINK = 3
    NIGHT_BOSS = 4


def format_period(seconds: int) -> str:
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"


class Updater(QObject):
    update_overlay_ui_state_signal = pyqtSignal(OverlayUIState)
    update_map_overlay_ui_state_signal = pyqtSignal(MapOverlayUIState)
    hp_overlay_ui_state_signal = pyqtSignal(HpOverlayUIState)
    input_block_signals_signal = pyqtSignal(bool)

    def __init__(
        self, 
        input: InputWorker,
        overlay: OverlayWidget, 
        map_overlay: MapOverlayWidget,
        hp_overlay: HpOverlayWidget,
    ):
        super().__init__()
        self._running = False

        self.is_setting_opened = False
        self.is_menu_opened = False

        self.detector = DetectorManager()
        self.only_detect_when_game_foreground: bool = False
        self.detect_interval = 0.2

        self.input_block_signals_signal.connect(input.blockSignals)

        self.overlay = overlay
        self.update_overlay_ui_state_signal.connect(self.overlay.update_ui_state)
        self.day: int = None
        self.current_phase: Phase = None
        self.phase_start_time: float = None
        self.dayx_detect_enabled: bool = True
        self.day1_detect_region = None
        self.dayx_detect_lang: str = "chs"
        
        self.in_rain_start_time: float = None
        self.in_rain_detect_enabled: bool = True
        self.hpcolor_detect_region: tuple[int] = None
        self.in_rain_hls: tuple[int] = None
        self.not_in_rain_hls: tuple[int] = None
        self.in_rain_hls_hdr: tuple[int] = None
        self.not_in_rain_hls_hdr: tuple[int] = None

        self.map_overlay = map_overlay
        self.update_map_overlay_ui_state_signal.connect(self.map_overlay.update_ui_state)
        self.map_detect_enabled: bool = True
        self.map_region: tuple[int] = None
        self.current_is_full_map: bool = False
        self.do_match_map_pattern_flag: DoMatchMapPatternFlag = DoMatchMapPatternFlag.TRUE
        self.map_pattern: MapPattern = None
        self.map_overlay_visible: bool = False
        self.last_map_pattern_match_time: float = 0.0

        self.hp_overlay = hp_overlay
        self.hp_overlay_ui_state_signal.connect(self.hp_overlay.update_ui_state)
        self.hp_detect_enabled: bool = True
        self.hp_detect_keep_last_valid: bool = False
        self.hpbar_region: tuple[int] = None
        self.hp_length: int = None

        self.art_detect_enabled: bool = False
        self.to_detect_art_time: float = 0.0
        self.art_start_time: float = 0.0
        self.art_region: tuple[int] = None
        self.art_type: str = None

        # HDR图像处理设置
        self.hdr_processing_enabled: bool = False


    def get_time(self) -> float:
        return time.time() * Config.get().time_scale

    # =============== Day and Phase Management =============== #

    def start_day1(self):
        self.day = 1
        self.current_phase = Phase.FIRST_CIRCLE_STABLE
        self.phase_start_time = self.get_time()
        info("Day 1 started.")
        self.set_to_detect_map_pattern_once()

    def start_day2(self):
        self.day = 2
        self.current_phase = Phase.FIRST_CIRCLE_STABLE
        self.phase_start_time = self.get_time()
        info("Day 2 started.")

    def start_day3(self):
        self.day = 3
        self.current_phase = Phase.NIGHT_BOSS
        self.phase_start_time = self.get_time()
        info("Day 3 started.")

    def start_day_by_shortcut(self):
        if self.day is None:
            self.start_day1()
            info("Day 1 started by shortcut.")
        elif self.day == 1:
            self.start_day2()
            info("Day 2 started by shortcut.")
        elif self.day == 2:
            self.start_day1()
            info("Day 1 started by shortcut.")

    def foward_day_by_shortcut(self):
        if self.phase_start_time is not None:
            self.phase_start_time -= Config.get().foward_day_seconds

    def back_day_by_shortcut(self):
        if self.phase_start_time is not None:
            self.phase_start_time += Config.get().back_day_seconds

    def get_phase_progress_text(self) -> tuple[float, str]:
        if self.day is None:
            progress = 0.0
            text = None
        elif self.day == 3:
            progress = 4.0
            t = self.get_time() - self.phase_start_time
            text = f"{format_period(int(t))}"
        elif self.current_phase == Phase.NIGHT_BOSS:
            progress = 4.0
            t = self.get_time() - self.phase_start_time
            text = f"夜晚BOSS战 {format_period(int(t))}"
        else:
            index = self.current_phase.value
            t = self.get_time() - self.phase_start_time
            total = Config.get().day_period_seconds[index]
            progress = t / total + index
            circle_no = "一" if index < 2 else "二"
            action_text = "开始缩圈" if index % 2 == 0 else "缩圈结束"
            text = f"{format_period(int(total - t))} 后第{circle_no}圈{action_text}"
        if self.day is not None:
            text = f"DAY {'I' * self.day} - " + text
        return progress, text
    
    def update_phase_timer(self):
        config = Config.get()
        if self.current_phase is not None:
            index = self.current_phase.value
            phase_length = None if index >= 4 else config.day_period_seconds[index]
            if phase_length is not None and self.get_time() - self.phase_start_time > phase_length:
                self.current_phase = Phase(self.current_phase.value + 1)
                self.phase_start_time += phase_length
                info(f"Phase progress to {self.current_phase.name}.")
            if self.get_time() < self.phase_start_time:
                if self.current_phase.value >= 1:
                    self.current_phase = Phase(self.current_phase.value - 1)
                    self.phase_start_time -= config.day_period_seconds[self.current_phase.value]
                    info(f"Phase back to {self.current_phase.name}.")
                else:
                    self.phase_start_time = self.get_time()

    def detect_and_update_dayx(self):
        if not self.dayx_detect_enabled:
            return
        param = DetectParam(
            day_detect_param=DayDetectParam(
                day1_region=self.day1_detect_region,
                lang=self.dayx_detect_lang,
                hdr_processing_enabled=self.hdr_processing_enabled,
            )
        )
        result = self.detector.detect(param)
        if result.day_detect_result.start_day1:
            self.start_day1()
        elif result.day_detect_result.start_day2:
            self.start_day2()
        elif result.day_detect_result.start_day3:
            self.start_day3()

    # =============== In Rain Management =============== #

    def start_in_rain(self):
        self.in_rain_start_time = self.get_time()
        info("Started in rain.")

    def stop_in_rain(self):
        self.in_rain_start_time = None
        info("Stopped in rain.")

    def start_in_rain_by_shortcut(self):
        if self.in_rain_start_time is None:
            self.start_in_rain()
            info("Started in rain by shortcut.")
        else:
            self.stop_in_rain()
            info("Stopped in rain by shortcut.")

    def get_in_rain_progress_text(self) -> tuple[float, str]:
        if self.in_rain_start_time is None:
            return 0, ""
        t = self.get_time() - self.in_rain_start_time
        total = Config.get().deadly_nightrain_seconds
        progress = 1.0 - min(t / total, 1.0)
        percent = int(100 * (1.0 - progress))
        text = f"雨中冒险倒计时 {format_period(int(max(total - t, 0)))} - {percent}%"
        return progress, text

    def detect_and_update_in_rain(self):
        if not self.in_rain_detect_enabled:
            return
        param = DetectParam(
            rain_detect_param=RainDetectParam(
                in_rain_hls=self.in_rain_hls,
                not_in_rain_hls=self.not_in_rain_hls,
                in_rain_hls_hdr=self.in_rain_hls_hdr,
                not_in_rain_hls_hdr=self.not_in_rain_hls_hdr,
                hpcolor_region=self.hpcolor_detect_region,
                hdr_processing_enabled=self.hdr_processing_enabled,
            )
        )
        result = self.detector.detect(param)
        is_in_rain = result.rain_detect_result.is_in_rain
        if is_in_rain is not None:
            if is_in_rain and self.in_rain_start_time is None:
                self.start_in_rain()
            if not is_in_rain and self.in_rain_start_time is not None:
                self.stop_in_rain()

    # =============== Map Pattern Management =============== #

    def set_to_detect_map_pattern_once(self):
        self.do_match_map_pattern_flag = DoMatchMapPatternFlag.PREPARE
        info("Set to detect map pattern once.")

    def update_overlay_match_map_pattern_text(self):
        match_ready = self.do_match_map_pattern_flag != DoMatchMapPatternFlag.FALSE and self.map_detect_enabled
        if match_ready:
            self.update_overlay_ui_state_signal.emit(OverlayUIState(
                map_pattern_match_text=" - 地图识别就绪",
            ))
        else:
            self.update_overlay_ui_state_signal.emit(OverlayUIState(
                map_pattern_match_text="",
            ))

    def update_map_overlay_image(self, image: Image.Image | None):
        if image is None:
            self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
                clear_image=True,
                map_pattern_match_time=0,
                map_pattern_matching=False,
            ))
            info("Clear map overlay image.")
        else:
            self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
                overlay_image=image,
                x=self.map_region[0],
                y=self.map_region[1],
                w=self.map_region[2],
                h=self.map_region[3],
                map_pattern_match_time=self.get_time(),
                map_pattern_matching=False,
            ))
            info("Update map overlay image.")

    def show_map_overlay(self):
        if not self.map_overlay_visible:
            self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
                opacity=1.0,
                x=self.map_region[0],
                y=self.map_region[1],
                w=self.map_region[2],
                h=self.map_region[3],
            ))
            self.map_overlay_visible = True
            info("Show map overlay.")

    def hide_map_overlay(self):
        if self.map_overlay_visible:
            self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
                opacity=0.0,
            ))
            self.map_overlay_visible = False
            info("Hide map overlay.")

    def show_or_hide_map_overlay_by_shortcut(self):
        if self.map_overlay_visible:
            self.hide_map_overlay()
        else:
            self.show_map_overlay()

    def detect_and_update_map(self):
        if not self.map_detect_enabled:
            self.hide_map_overlay()
            return
   
        param = DetectParam(
            map_detect_param=MapDetectParam(
                map_region=self.map_region,
                do_match_full_map=True,
                hdr_processing_enabled=self.hdr_processing_enabled,
            )
        )
        result = self.detector.detect(param)

        is_full_map = result.map_detect_result.is_full_map
        map_img = result.map_detect_result.img
        if is_full_map is not None:
            if is_full_map and not self.current_is_full_map:
                info("Current map changed to full map.")
                self.current_is_full_map = True
                self.show_map_overlay()
            if not is_full_map and self.current_is_full_map:
                info("Current map changed to non-full map.")
                self.current_is_full_map = False
                self.hide_map_overlay()

        self.update_overlay_match_map_pattern_text()
        if self.get_time() - self.last_map_pattern_match_time > Config.get().map_pattern_match_interval:
            self.set_to_detect_map_pattern_once()
            self.last_map_pattern_match_time = self.get_time()
            info("Set to detect map pattern once by interval.")

        if self.do_match_map_pattern_flag == DoMatchMapPatternFlag.PREPARE:
            # 隐藏信息显示，等待下一次更新进行识别
            self.do_match_map_pattern_flag = DoMatchMapPatternFlag.TRUE
            self.update_map_overlay_image(None)
            info("Hide overlay and prepared to detect map pattern.")

        elif self.do_match_map_pattern_flag == DoMatchMapPatternFlag.TRUE and is_full_map:
            # 特殊地形识别成功才进行匹配（避免地图半透明时就识别）
            result = self.detector.detect(DetectParam(
                map_detect_param=MapDetectParam(
                    map_region=self.map_region,
                    img=map_img,    # 使用之前截取的图片，避免处理过程中画面变化
                    do_match_earth_shifting=True,
                    hdr_processing_enabled=self.hdr_processing_enabled,
                )
            ))
            earth_shifting = result.map_detect_result.earth_shifting
            if earth_shifting is not None:
                # 进行匹配
                self.do_match_map_pattern_flag = DoMatchMapPatternFlag.FALSE
                self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
                    clear_image=True,
                    map_pattern_matching=True,
                    x=self.map_region[0],
                    y=self.map_region[1],
                    w=self.map_region[2],
                    h=self.map_region[3],
                    opacity=1.0,
                ))
                self.update_overlay_ui_state_signal.emit(OverlayUIState(
                    map_pattern_match_text="",
                ))
                result = self.detector.detect(DetectParam(
                    map_detect_param=MapDetectParam(
                        map_region=self.map_region,
                        img=map_img,
                        earth_shifting=earth_shifting,
                        do_match_pattern=True,
                        hdr_processing_enabled=self.hdr_processing_enabled,
                    )
                ))
                self.map_pattern = result.map_detect_result.pattern
                self.update_map_overlay_image(result.map_detect_result.overlay_image)
                self.last_map_pattern_match_time = self.get_time()

    # =============== HP Management =============== #

    def update_hp_length(self, length: int | None):
        if length is None or length <= 0:
            self.hp_overlay_ui_state_signal.emit(HpOverlayUIState(
                visible=False,
            ))
        else:
            self.hp_overlay_ui_state_signal.emit(HpOverlayUIState(
                visible=True,
                x=self.hpbar_region[0],
                y=self.hpbar_region[1],
                h=self.hpbar_region[3],
                w=length,
            ))

    def detect_and_update_hp(self):
        if not self.hp_detect_enabled:
            self.update_hp_length(None)
            return
        
        param = DetectParam(
            hp_detect_param=HpDetectParam(
                hpbar_region=self.hpbar_region,
                keep_last_valid=self.hp_detect_keep_last_valid,
            )
        )
        result = self.detector.detect(param)

        hp_length = result.hp_detect_result.hpbar_length
        if hp_length is not None:
            self.hp_length = hp_length
            self.update_hp_length(self.hp_length)

    # =============== Art Management =============== #

    def use_art_by_shortcut(self):
        config = Config.get()
        self.to_detect_art_time = self.get_time() + config.art_detect_delay_seconds
        info(f"Will detect art in {config.art_detect_delay_seconds} seconds.")
    
    def detect_and_update_art(self):
        if not self.art_detect_enabled or \
            self.to_detect_art_time is None or self.get_time() < self.to_detect_art_time:
            return
        
        param = DetectParam(
            art_detect_param=ArtDetectParam(
                art_region=self.art_region,
                hdr_processing_enabled=self.hdr_processing_enabled,
            )
        )
        result = self.detector.detect(param)
        self.to_detect_art_time = None
        
        if result.art_detect_result.art_type is None:
            info("No art detected.")
            return
        
        info(f"detected art: {result.art_detect_result.art_type}")
        self.art_type = result.art_detect_result.art_type
        self.art_start_time = self.get_time()

    def get_art_progress_text_color(self) -> tuple[float, str, str]:
        if self.art_type is None or self.art_start_time is None:
            return 0.0, "", None
        
        config = Config.get()
        info = config.art_info[self.art_type]
        delay = info.get("delay", 0)
        duration = info.get("duration", 0)
        text = info.get("text", "")
        color = info.get("color", "#ffffff")

        t = max(0, self.get_time() - self.art_start_time - delay)
        if t > duration:
            self.art_type = None
            self.art_start_time = None
            return 0.0, "", None
        
        progress = 1.0 - t / duration
        text = f"{text} {format_period(int(max(duration - t, 0)))}"
        return progress, text, color
        
    # =============== Main Loop =============== #

    def detect_and_update_all(self):
        self.detect_and_update_dayx()
        self.detect_and_update_in_rain()
        self.detect_and_update_map()
        self.detect_and_update_hp()
        self.detect_and_update_art()

    def check_game_foreground(self) -> bool:
        is_foreground = is_window_in_foreground(GAME_WINDOW_TITLE)
        
        self.update_overlay_ui_state_signal.emit(OverlayUIState(
            is_game_foreground=is_foreground,
        ))
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
            is_game_foreground=is_foreground,
        ))
        self.hp_overlay_ui_state_signal.emit(HpOverlayUIState(
            is_game_foreground=is_foreground,
        ))

        self.input_block_signals_signal.emit(self.only_detect_when_game_foreground and \
            not (is_foreground or self.is_setting_opened or self.is_menu_opened))
        
        return is_foreground

    def run(self):
        try:
            self._running = True
            info("Updater started.")

            last_detect_time = 0
            while self._running:
                start_time = self.get_time()

                is_game_foreground = self.check_game_foreground()

                if self.get_time() - last_detect_time > self.detect_interval:
                    if not self.only_detect_when_game_foreground or is_game_foreground:
                        self.detect_and_update_all()
                    last_detect_time = self.get_time()

                self.update_phase_timer()
                day_progress, day_text = self.get_phase_progress_text()
                rain_progress, rain_text = self.get_in_rain_progress_text()
                art_progress, art_text, art_color = self.get_art_progress_text_color()

                self.update_overlay_ui_state_signal.emit(OverlayUIState(
                    day_progress=day_progress,
                    day_text=day_text,
                    rain_progress=rain_progress,
                    rain_text=rain_text,
                    rain_progress_visible=rain_progress > 0.0,
                    art_progress=art_progress,
                    art_text=art_text,
                    art_progress_visible=art_progress > 0.0,
                    art_color=art_color,
                ))

                elapsed = self.get_time() - start_time
                sleep_time = Config.get().update_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except Exception as e:
            error(f"Exception in updater run: {e}")
            raise e
        info("Updater stopped.")

    def stop(self):
        self._running = False


