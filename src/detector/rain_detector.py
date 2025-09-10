import cv2
import numpy as np
from dataclasses import dataclass
from PIL import Image
import time
from PyQt6.QtGui import QPixmap
from mss.base import MSSBase

from src.config import Config
from src.logger import error
from src.detector.utils import grab_region


@dataclass
class RainDetectParam:
    in_rain_hls: tuple[int, int, int] | None = None
    not_in_rain_hls: tuple[int, int, int] | None = None
    hp_bar_region: tuple[int] | None = None


@dataclass
class RainDetectResult:
    is_in_rain: bool | None = None
    in_rain_area_ratio: float = None
    not_in_rain_area_ratio: float = None


class RainDetector:
    def __init__(self):
        pass

    def match(
        self,
        sct,
        hp_bar_region: tuple[int],
        in_rain_hls: tuple[int] | None,
        not_in_rain_hls: tuple[int] | None,
    ) -> tuple[float, float]:
        try:
            t = time.time()
            config = Config.get()

            img = grab_region(sct, hp_bar_region)
            hls = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2HLS)
            # print(hls[hls.shape[0]//2, hls.shape[1]//2])

            def calc_pixel_num(hls: np.ndarray, c1: list[int], c2: list[int]) -> int:
                lower = np.array([min(c1[i], c2[i]) for i in range(3)])
                upper = np.array([max(c1[i], c2[i]) for i in range(3)])
                tolerance = np.array(
                    [config.h_tolerance, config.l_tolerance, config.s_tolerance]
                )
                lower = lower - tolerance
                upper = upper + tolerance
                mask = cv2.inRange(hls, lower, upper)
                return np.sum(mask > 0)

            total_pixel_num = hls.shape[0] * hls.shape[1]

            lower_hls_not_in_rain = (
                not_in_rain_hls
                if not_in_rain_hls is not None
                else config.lower_hls_not_in_rain
            )
            upper_hls_not_in_rain = (
                not_in_rain_hls
                if not_in_rain_hls is not None
                else config.upper_hls_not_in_rain
            )
            lower_hls_in_rain = (
                in_rain_hls if in_rain_hls is not None else config.lower_hls_in_rain
            )
            upper_hls_in_rain = (
                in_rain_hls if in_rain_hls is not None else config.upper_hls_in_rain
            )

            not_in_rain_ratio = (
                calc_pixel_num(hls, lower_hls_not_in_rain, upper_hls_not_in_rain)
                / total_pixel_num
            )
            in_rain_ratio = (
                calc_pixel_num(hls, lower_hls_in_rain, upper_hls_in_rain)
                / total_pixel_num
            )

            # print(f"{not_in_rain_ratio:.2f}, {in_rain_ratio:.2f}")
            # print("detect in rain time: ", time.time() - t)
            return not_in_rain_ratio, in_rain_ratio
        except Exception:
            error("Detect in rain error")
            return 0.0, 0.0

    def detect(self, sct: MSSBase, params: RainDetectParam | None) -> RainDetectResult:
        config = Config.get()
        ret = RainDetectResult()
        if params is None or params.hp_bar_region is None:
            return ret
        not_in_rain_ratio, in_rain_ratio = self.match(
            sct, params.hp_bar_region, params.in_rain_hls, params.not_in_rain_hls
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
        hp_bar_region = hls[
            region[1] : region[1] + region[3], region[0] : region[0] + region[2]
        ]
        hist = cv2.calcHist(
            [hp_bar_region], [0, 1, 2], None, [180, 256, 256], [0, 180, 0, 256, 0, 256]
        )
        max_val = np.unravel_index(np.argmax(hist), hist.shape)
        return [int(x) for x in max_val]
