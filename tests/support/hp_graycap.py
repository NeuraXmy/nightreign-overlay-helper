"""Experimental region-based HP boundary detector for gray cap-loss footage."""

from __future__ import annotations

from collections import deque

import numpy as np


class GrayCapHpExperiment:
    """Find the usable endpoint from a short RGB crop including the whole bar."""

    def __init__(self) -> None:
        self._recent: deque[tuple[int, bool]] = deque(maxlen=5)
        self._shape: tuple[int, ...] | None = None

    def detect(self, image: np.ndarray) -> int | None:
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            self.__init__()
            return None
        if image.shape != self._shape:
            self.__init__()
            self._shape = image.shape
        if image.shape[0] < 8 or image.shape[1] < 100:
            self.__init__()
            return None

        feature = _feature(image)
        if feature is None:
            self._recent.clear()
            return None
        self._recent.append(feature)
        if len(self._recent) < 3:
            return None

        endpoints = [endpoint for endpoint, _gray in self._recent]
        stable_endpoint = int(np.median(endpoints[-3:]))
        if max(endpoints[-3:]) - min(endpoints[-3:]) > 3:
            return None
        gray_votes = sum(gray for _endpoint, gray in self._recent)
        # Use the gray boundary only when it is present in a majority of recent
        # frames; otherwise the terminal cap is the usable maximum endpoint.
        if gray_votes >= 3:
            return stable_endpoint
        return stable_endpoint


def _feature(image: np.ndarray) -> tuple[int, bool] | None:
    rgb = image.astype(np.float32)
    width = image.shape[1]

    # The HP bar starts close to the crop origin. Locate its horizontal row band
    # from the red fill rather than assuming an absolute screen y coordinate.
    prefix = rgb[:, 6 : min(width, 50)]
    warmth = prefix[:, :, 0] - np.maximum(prefix[:, :, 1], prefix[:, :, 2])
    row_score = np.quantile(warmth, 0.75, axis=1)
    max_score = float(row_score.max())
    if max_score < 12:
        return None
    rows = np.flatnonzero(row_score > max(8, 0.45 * max_score))
    if len(rows) < 5:
        return None
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    group = max(groups, key=len)
    top, bottom = int(group[0]), int(group[-1]) + 1
    if bottom - top < 6:
        return None
    body_top, body_bottom = top + 1, bottom - 1
    if body_bottom - body_top < 3:
        body_top, body_bottom = top, bottom

    band = rgb[body_top:body_bottom]
    lum = np.median(band.mean(axis=2), axis=0)
    chroma = np.median(np.ptp(band, axis=2), axis=0)

    # The leftmost bright vertical cap establishes the bar origin.
    start = int(np.argmax(lum[: min(12, width)]))
    minimum = start + max(32, width // 12)
    maximum = width - max(8, width // 30)
    if maximum <= minimum:
        return None

    # Vertical cap highlights rise above both nearby sides. This captures the
    # gray-limit divider and the outer cap without pinning a color palette.
    candidates: list[tuple[int, float]] = []
    for x in range(minimum, maximum):
        left = lum[max(minimum, x - 7) : max(minimum, x - 2)]
        right = lum[x + 3 : min(maximum, x + 8)]
        if len(left) < 2 or len(right) < 2:
            continue
        side = max(float(np.median(left)), float(np.median(right)))
        peak = float(lum[x])
        response = peak - side
        if response >= max(12, 0.13 * float(np.median(lum[minimum:maximum]))) and chroma[x] < 35:
            candidates.append((x, response))

    # Collapse adjacent bright pixels into one cap. Prefer the highest central
    # pixel, then require an actual falling edge to suppress wide scene highlights.
    caps: list[tuple[int, float]] = []
    for x, response in candidates:
        if caps and x - caps[-1][0] <= 4:
            if response > caps[-1][1]:
                caps[-1] = (x, response)
            continue
        caps.append((x, response))
    if not caps:
        return None

    # Ignore isolated fill highlights: a cap has a neutral, bright vertical
    # ridge and stays above its local background for several neighboring rows.
    caps = [
        (x, score)
        for x, score in caps
        if float(np.median(chroma[max(0, x - 2) : x + 3])) < 35
        and float(np.median(lum[max(0, x - 2) : x + 3]))
        > max(float(np.median(lum[max(0, x - 12) : x - 4])), float(np.median(lum[x + 4 : x + 12]))) + 5
    ]
    if not caps:
        return None

    # Gray cap-loss has a dark empty gap followed by a neutral, brighter span
    # inside the same outlined bar. It is an internal vertical divider, so a
    # later outer cap must also be present.
    gray_caps: list[int] = []
    for x, _score in caps[:-1]:
        before = lum[max(start + 16, x - 34) : x - 8]
        after = lum[x + 8 : min(width, x + 42)]
        before_chroma = chroma[max(start + 16, x - 34) : x - 8]
        after_chroma = chroma[x + 8 : min(width, x + 42)]
        if min(len(before), len(after)) < 12:
            continue
        dark_empty = float(np.median(before)) < 68 and float(np.median(before_chroma)) < 28
        gray_fill = (
            float(np.median(after)) > float(np.median(before)) + 18 and float(np.median(after_chroma)) < 18
        )
        if dark_empty and gray_fill:
            gray_caps.append(x)

    endpoint = gray_caps[0] if gray_caps else caps[-1][0]
    # Return the boundary relative to the crop's left edge; callers calibrate
    # the crop at the bar's left cap as in the deployed plugin.
    return endpoint, bool(gray_caps)
