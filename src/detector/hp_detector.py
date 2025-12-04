import cv2
import numpy as np
from dataclasses import dataclass
from PIL import Image
import time
from PyQt6.QtGui import QPixmap
from mss.base import MSSBase

from src.config import Config
from src.logger import info, warning, error, debug
from src.detector.utils import grab_region, resize_by_height_keep_aspect_ratio


@dataclass
class HpDetectParam:
    hpbar_region: tuple[int] | None = None

@dataclass
class HpDetectResult:
    hpbar_length: int | None = None


class HpDetector:
    def __init__(self):
        self.recent_lengths: list[int] = []

    def detect(self, sct: MSSBase, params: HpDetectParam | None) -> HpDetectResult:
        if params is None or params.hpbar_region is None:
            return HpDetectResult()
        config = Config.get()
        ret = HpDetectResult()

        t = time.time()
        x, y, w, h = params.hpbar_region
        w = h * config.hpbar_region_aspect_ratio
        img = grab_region(sct, (x, y, w, h), processing='none')
        original_w = img.width
        img = resize_by_height_keep_aspect_ratio(img, config.hpbar_detect_std_height)
        hsv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2HSV)

        # 截取中线的亮度
        mid_y = hsv.shape[0] // 2
        vals = hsv[mid_y, :, 2].astype(int)

        # 绘制V通道用于调试
        # debug_img = np.zeros((100, vals.shape[0], 3), dtype=np.uint8)
        # for i in range(vals.shape[0]):
        #     cv2.line(debug_img, (i, 100), (i, 100 - vals[i] * 100 // 255), (255, 255, 255), 1)

        peak_num = 0
        start = config.hpbar_border_v_peak_start
        lower = config.hpbar_border_v_peak_lower
        threshold = config.hpbar_border_v_peak_threshold
        interval = config.hpbar_border_v_peak_interval
        last_is_peak = False
        length = None

        # 检测亮度快速提升的尖峰
        for i in range(start, len(vals)):
            cur_is_peak = False
            for j in range(0, interval):
                if vals[i] - vals[i - j] > threshold and vals[i] > lower:
                    cur_is_peak = True
                    break   
            if cur_is_peak:
                length = int(i * original_w / img.width)
                # cv2.circle(debug_img, (i, 100 - vals[i] * 100 // 255), 2, (0, 0, 255), -1)
            if cur_is_peak and not last_is_peak:
                peak_num += 1
                if peak_num == 2:
                    # cv2.line(debug_img, (i, 0), (i, 100), (0, 255, 0), 1)
                    break
            last_is_peak = cur_is_peak

        if length and peak_num == 2:
            length += 2

        self.recent_lengths.append(length if length else -1)
        if len(self.recent_lengths) > config.hpbar_recent_length_count:
            self.recent_lengths.pop(0)
        # 找出众数
        counts = {}
        for l in self.recent_lengths:
            counts[l] = counts.get(l, 0) + 1
        most_common_length = max(counts, key=counts.get)
        if counts[most_common_length] < config.hpbar_recent_length_count // 2:
            most_common_length = None
        else:
            ret.hpbar_length = most_common_length

        # debug_img = cv2.resize(debug_img, (img.width, debug_img.shape[0]))
        # debug_img = cv2.vconcat([np.array(img), debug_img])
        # cv2.imwrite("sandbox/debug_hpbar_v_channel.png", debug_img)
        
        debug(f"HpDetector: lengths={self.recent_lengths}, time={time.time() - t:.3f}s")
        return ret
    


