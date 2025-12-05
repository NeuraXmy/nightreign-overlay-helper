import cv2
import numpy as np
from dataclasses import dataclass
from PIL import Image
import time
from PyQt6.QtGui import QPixmap
from mss.base import MSSBase

from src.config import Config
from src.logger import info, warning, error, debug
from src.detector.utils import grab_region


@dataclass
class RainDetectParam:
    in_rain_hls: tuple[int, int, int] | None = None
    not_in_rain_hls: tuple[int, int, int] | None = None
    in_rain_hls_hdr: tuple[int, int, int] | None = None
    not_in_rain_hls_hdr: tuple[int, int, int] | None = None
    hpcolor_region: tuple[int] | None = None
    hdr_processing_enabled: bool = False

@dataclass
class RainDetectResult:
    is_in_rain: bool | None = None
    in_rain_area_ratio: float = None
    not_in_rain_area_ratio: float = None



class RainDetector:
    def __init__(self):
        pass
        
    def match(
        self, sct, 
        hpcolor_region: tuple[int],
        in_rain_hls: tuple[int] | None,
        not_in_rain_hls: tuple[int] | None,
        in_rain_hls_hdr: tuple[int] | None,
        not_in_rain_hls_hdr: tuple[int] | None,
        hdr_processing_enabled: bool = False,
    ) -> tuple[float, float]:
        try:
            t = time.time()
            config = Config.get()

            img = grab_region(sct, hpcolor_region, processing='none')
            hls = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2HLS)

            def calc_pixel_num(hls: np.ndarray, c1: list[int], c2: list[int]) -> int:
                lower = np.array([min(c1[i], c2[i]) for i in range(3)])
                upper = np.array([max(c1[i], c2[i]) for i in range(3)])
                tolerance = np.array([config.h_tolerance, config.l_tolerance, config.s_tolerance])
                lower = lower - tolerance
                upper = upper + tolerance
                mask = cv2.inRange(hls, lower, upper)
                return np.sum(mask > 0)
                
            total_pixel_num = hls.shape[0] * hls.shape[1]

            # 根据HDR模式选择配置
            if hdr_processing_enabled:
                lower_hls_not_in_rain = not_in_rain_hls_hdr if not_in_rain_hls_hdr is not None else config.lower_hls_not_in_rain_hdr
                upper_hls_not_in_rain = not_in_rain_hls_hdr if not_in_rain_hls_hdr is not None else config.upper_hls_not_in_rain_hdr
                lower_hls_in_rain = in_rain_hls_hdr if in_rain_hls_hdr is not None else config.lower_hls_in_rain_hdr
                upper_hls_in_rain = in_rain_hls_hdr if in_rain_hls_hdr is not None else config.upper_hls_in_rain_hdr
            else:
                lower_hls_not_in_rain = not_in_rain_hls if not_in_rain_hls is not None else config.lower_hls_not_in_rain
                upper_hls_not_in_rain = not_in_rain_hls if not_in_rain_hls is not None else config.upper_hls_not_in_rain
                lower_hls_in_rain = in_rain_hls if in_rain_hls is not None else config.lower_hls_in_rain
                upper_hls_in_rain = in_rain_hls if in_rain_hls is not None else config.upper_hls_in_rain

            not_in_rain_ratio = calc_pixel_num(hls, lower_hls_not_in_rain, upper_hls_not_in_rain) / total_pixel_num
            in_rain_ratio     = calc_pixel_num(hls, lower_hls_in_rain,     upper_hls_in_rain)     / total_pixel_num

            debug(f"RainDetector: cost: {time.time() - t:.3f}s, not_in_rain_ratio={not_in_rain_ratio:.3f}, in_rain_ratio={in_rain_ratio:.3f}")
            return not_in_rain_ratio, in_rain_ratio
        except Exception as e:
            error(f"Detect in rain error")
            return 0.0, 0.0

    def detect(self, sct: MSSBase, params: RainDetectParam | None) -> RainDetectResult:
        config = Config.get()
        ret = RainDetectResult()
        if params is None or params.hpcolor_region is None:
            return ret
        not_in_rain_ratio, in_rain_ratio = self.match(
            sct, 
            params.hpcolor_region, 
            params.in_rain_hls, 
            params.not_in_rain_hls,
            params.in_rain_hls_hdr,
            params.not_in_rain_hls_hdr,
            params.hdr_processing_enabled
        )
        ret.not_in_rain_area_ratio = not_in_rain_ratio
        ret.in_rain_area_ratio = in_rain_ratio
        min_ratio = config.hp_color_min_area_ratio
        max_ratio = config.hp_color_max_area_ratio
        if in_rain_ratio >= max_ratio and not_in_rain_ratio <= min_ratio:
            ret.is_in_rain = True
        elif not_in_rain_ratio >= max_ratio and in_rain_ratio <= min_ratio:
            ret.is_in_rain = False
        return ret

    @staticmethod
    def get_to_detect_hp_hls(screenshot: QPixmap, region: tuple[int]) -> tuple[int]:
        img = Image.fromqpixmap(screenshot)
        hls = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2HLS)
        hpcolor_region = hls[region[1]:region[1]+region[3], region[0]:region[0]+region[2]]
        hist = cv2.calcHist([hpcolor_region], [0, 1, 2], None, [180, 256, 256], [0, 180, 0, 256, 0, 256])
        max_val = np.unravel_index(np.argmax(hist), hist.shape)
        return [int(x) for x in max_val]


