"""Legacy HP-border brightness detection and history stabilization, with raw RGB input."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from nightreign_overlay.plugins.hp_marker.config import HpDetectionSettings


class HpDetector:
    def __init__(self) -> None:
        self.recent_lengths: list[int] = []
        self.last_valid_length: int | None = None
        self.stable_count = 0

    def detect(self, image: np.ndarray, config: HpDetectionSettings) -> int | None:
        """Detect the full HP bar length; input is the unprocessed, expanded region crop."""
        original_w = image.shape[1]
        source = Image.fromarray(image)
        size = (
            int(config.hpbar_detect_std_height * (source.width / source.height)),
            config.hpbar_detect_std_height,
        )
        # PIL LANCZOS is intentional: changing the filter changes brightness peaks.
        img = source.resize(size, Image.Resampling.LANCZOS)
        ret = _Result()
        hsv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2HSV)

        mid_y = hsv.shape[0] // 2
        vals = hsv[mid_y, :, 2].astype(int)

        peak_num = 0
        start = config.hpbar_border_v_peak_start
        lower = config.hpbar_border_v_peak_lower
        threshold = config.hpbar_border_v_peak_threshold
        interval = config.hpbar_border_v_peak_interval
        last_is_peak = False
        length = None
        peak_positions = []  # 记录所有尖峰位置

        for i in range(start, len(vals)):
            cur_is_peak = False
            peak_score = 0
            for j in range(1, min(interval, i)):
                if vals[i] - vals[i - j] > threshold and vals[i] > lower:
                    peak_score += 1
            cur_is_peak = peak_score >= interval // 2

            if cur_is_peak:
                length = int(i * original_w / img.width)
            if cur_is_peak and not last_is_peak:
                peak_num += 1
                peak_positions.append(i)
                if peak_num == 2:
                    break
            last_is_peak = cur_is_peak

        if length and peak_num == 2:
            length += 2

        self.recent_lengths.append(length if length else -1)
        if len(self.recent_lengths) > config.hpbar_recent_length_count:
            self.recent_lengths.pop(0)

        valid_lengths = [sample for sample in self.recent_lengths if sample > 0]
        if len(valid_lengths) >= config.hpbar_recent_length_count // 3:
            clustered_counts = {}
            for sample in valid_lengths:
                found_cluster = False
                for key in list(clustered_counts.keys()):
                    if abs(sample - key) <= 3:
                        clustered_counts[key].append(sample)
                        found_cluster = True
                        break
                if not found_cluster:
                    clustered_counts[sample] = [sample]

            if clustered_counts:
                max_cluster_key = max(clustered_counts, key=lambda k: len(clustered_counts[k]))
                cluster = clustered_counts[max_cluster_key]
                if len(cluster) >= len(self.recent_lengths) // 3:
                    most_common_length = int(np.mean(cluster))

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
                    if self.last_valid_length is not None and self.stable_count > 3:
                        ret.hpbar_length = self.last_valid_length
        else:
            if self.last_valid_length is not None and self.stable_count > 5:
                ret.hpbar_length = self.last_valid_length

        return ret.hpbar_length


class _Result:
    hpbar_length: int | None = None
