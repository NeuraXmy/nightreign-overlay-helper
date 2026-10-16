"""Experimental multirow HP cap detector; deliberately not wired to the plugin.

Input includes the bar's upper/lower edges and some margin on all four sides.
This experiment measures the outer rectangle only: limit-loss gray segments
require separate labeled footage before this can replace usable-HP detection.
"""

from collections import deque

import numpy as np


class RectangleHpExperiment:
    def __init__(self) -> None:
        self._profiles: deque[np.ndarray] = deque(maxlen=5)
        self._shape: tuple[int, ...] | None = None
        self._endpoint: int | None = None
        self._misses = 0
        self.box: tuple[int, int, int, int] | None = None

    def detect(self, image: np.ndarray) -> int | None:
        self.box = None
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            self.__init__()
            return None
        if image.shape != self._shape:
            self.__init__()
            self._shape = image.shape
        height, width = image.shape[:2]
        if height < 10 or width < 100:
            self.__init__()
            return None
        rgb = image.astype(np.float32)
        # Locate the HP interior near the calibrated start. Color distinguishes
        # it from the FP/stamina bars; it never determines the horizontal endpoint.
        prefix = rgb[:, 8:36]
        warm = prefix[:, :, 0] - np.maximum(prefix[:, :, 1], prefix[:, :, 2])
        evidence = np.quantile(warm, 0.75, axis=1)
        rows = np.flatnonzero(evidence > max(8, 0.55 * float(evidence.max())))
        if not len(rows):
            self.__init__()
            return None
        groups = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
        group = max(groups, key=len)
        top, bottom = int(group[0]), min(height - 1, int(group[-1]) + 2)
        if bottom - top < 5 or top == 0 or bottom >= height - 1:
            self.__init__()
            return None
        band = rgb[top:bottom]
        gray, chroma = band.mean(axis=2), np.ptp(band, axis=2)
        start = int(np.argmax(gray[:, :24].mean(axis=0)))
        # Reject vanished/occluded left caps rather than recycling old geometry.
        contrast = gray[:, max(0, start - 1) : start + 4].max(axis=1) - np.median(
            gray[:, start + 12 : start + 47], axis=1
        )
        if float(np.median(contrast)) < 15:
            self.__init__()
            return None
        contrast = np.maximum(15, contrast)
        color = max(10, float(np.median(chroma[:, start + 12 : start + 47])))
        smooth = (np.roll(gray, 1, axis=1) + gray + np.roll(gray, -1, axis=1)) / 3
        ridge = gray - np.maximum(np.roll(smooth, 3, axis=1), np.roll(smooth, -3, axis=1))
        response = ridge / contrast[:, None] * np.clip(1 - chroma / color, 0, 1)
        response[:, : start + 40] = 0
        response[:, -20:] = 0
        # At least 3/4 of the rectangle's rows must support the vertical cap.
        # Acquisition is stricter about neutral color than current verification.
        verification = np.quantile(response, 0.25, axis=0)
        response[chroma > max(8, 0.2 * color)] = 0
        profile = np.quantile(response, 0.25, axis=0)
        # Red/pink fill continuing beyond a candidate proves that it is an
        # internal division, even if the division's highlight looks neutral.
        warmth = np.median(band[:, :, 0] - np.maximum(band[:, :, 1], band[:, :, 2]), axis=0)
        continuation = np.zeros(width, dtype=bool)
        windows = np.lib.stride_tricks.sliding_window_view(warmth, 12)
        continuation[: width - 19] = np.median(windows[8 : width - 11], axis=1) > max(8, 0.15 * color)
        profile[continuation] = 0
        # A rectangle must retain a coherent lower rim across its interior and
        # that rim must stop after the terminal cap. This rejects pink/empty
        # divisions and isolated scenery ridges beyond the actual rectangle.
        rim = gray[-2:].mean(axis=0) - gray[2:-2].mean(axis=0)
        supported = rim > 6
        counts = np.cumsum(supported)
        xs = np.arange(width)
        inner_support = (counts - counts[min(width - 1, start + 12)]) / np.maximum(1, xs - start - 12)
        outside_support = np.zeros(width)
        outside_windows = np.lib.stride_tricks.sliding_window_view(supported, 24)
        outside_support[: width - 31] = outside_windows[8 : width - 23].mean(axis=1)
        profile[(inner_support < 0.75) | (outside_support > 0.8)] = 0
        self._profiles.append(profile)
        if len(self._profiles) == self._profiles.maxlen:
            consensus = np.quantile(np.stack(self._profiles), 0.25, axis=0)
            candidate = int(consensus.argmax())
            strength = float(consensus[candidate])
            consensus[max(0, candidate - 5) : candidate + 6] = 0
            if (
                strength > 0.1
                and strength > 1.5 * max(0, float(consensus.max()))
                and (self._endpoint is None or abs(candidate - self._endpoint) <= 3)
            ):
                self._endpoint = candidate
        if self._endpoint is not None:
            endpoint = self._endpoint
            if float(verification[endpoint - 2 : endpoint + 3].max()) > 0.01:
                self._misses = 0
                self.box = (start, top, endpoint, bottom)
                return endpoint - start
        self._misses += 1
        if self._misses >= 10:
            self._endpoint = None
            self._misses = 0
        return None
