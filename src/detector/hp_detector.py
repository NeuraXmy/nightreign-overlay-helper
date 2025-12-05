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
    keep_last_valid: bool = False

@dataclass
class HpDetectResult:
    hpbar_length: int | None = None


class HpDetector:
    def __init__(self):
        self.recent_lengths: list[int] = []
        self.last_valid_length: int | None = None
        self.stable_count: int = 0

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
        peak_positions = []  # 记录所有尖峰位置

        # 检测亮度快速提升的尖峰
        for i in range(start, len(vals)):
            cur_is_peak = False
            # 改进：检查亮度提升的稳定性
            peak_score = 0
            for j in range(1, min(interval, i)):
                if vals[i] - vals[i - j] > threshold and vals[i] > lower:
                    peak_score += 1
            # 要求至少有interval//2次满足条件
            cur_is_peak = peak_score >= interval // 2
            
            if cur_is_peak:
                length = int(i * original_w / img.width)
                # cv2.circle(debug_img, (i, 100 - vals[i] * 100 // 255), 2, (0, 0, 255), -1)
            if cur_is_peak and not last_is_peak:
                peak_num += 1
                peak_positions.append(i)
                if peak_num == 2:
                    # cv2.line(debug_img, (i, 0), (i, 100), (0, 255, 0), 1)
                    break
            last_is_peak = cur_is_peak

        if length and peak_num == 2:
            length += 2

        self.recent_lengths.append(length if length else -1)
        if len(self.recent_lengths) > config.hpbar_recent_length_count:
            self.recent_lengths.pop(0)
        
        # 改进的众数统计：考虑相近值的聚合
        valid_lengths = [l for l in self.recent_lengths if l > 0]
        if len(valid_lengths) >= config.hpbar_recent_length_count // 3:
            # 将相近的值（±3像素）聚合在一起
            clustered_counts = {}
            for l in valid_lengths:
                # 找到最接近的已有键
                found_cluster = False
                for key in list(clustered_counts.keys()):
                    if abs(l - key) <= 3:
                        clustered_counts[key].append(l)
                        found_cluster = True
                        break
                if not found_cluster:
                    clustered_counts[l] = [l]
            
            # 找出最大的簇
            if clustered_counts:
                max_cluster_key = max(clustered_counts, key=lambda k: len(clustered_counts[k]))
                cluster = clustered_counts[max_cluster_key]
                # 要求至少有1/3的样本支持
                if len(cluster) >= len(self.recent_lengths) // 3:
                    # 使用簇内的平均值作为最终结果
                    most_common_length = int(np.mean(cluster))
                    
                    # 平滑过渡：如果与上次结果接近，则使用加权平均
                    if self.last_valid_length is not None:
                        if abs(most_common_length - self.last_valid_length) <= 5:
                            most_common_length = int(0.7 * self.last_valid_length + 0.3 * most_common_length)
                            self.stable_count += 1
                        else:
                            self.stable_count = 0
                    else:
                        self.stable_count = 0
                    
                    self.last_valid_length = most_common_length
                    ret.hpbar_length = most_common_length
                else:
                    # 如果没有足够支持，保持上一个有效值
                    if self.last_valid_length is not None and self.stable_count > 3:
                        ret.hpbar_length = self.last_valid_length
        else:
            # 样本不足时，如果之前有稳定的值，继续使用
            if self.last_valid_length is not None and self.stable_count > 5:
                ret.hpbar_length = self.last_valid_length

        # debug_img = cv2.resize(debug_img, (img.width, debug_img.shape[0]))
        # debug_img = cv2.vconcat([np.array(img), debug_img])
        # cv2.imwrite("sandbox/debug_hpbar_v_channel.png", debug_img)
        
        debug(f"HpDetector: lengths={self.recent_lengths}, time={time.time() - t:.3f}s")
        return ret
    


