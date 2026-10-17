"""Ordered material segmentation with independent cap and outer-geometry evidence."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from nightreign_overlay.plugins.hp_marker.material_features import cap_features, material_features


@dataclass(frozen=True)
class MaterialBoundary:
    """Coordinates relative to the capture's left edge, including any existing inset."""

    top: int
    bottom: int
    outer: int | None
    usable: int | None


def _section(image: np.ndarray, scanline_y: int | None) -> tuple[int, int] | None:
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        return None
    height, width = image.shape[:2]
    if height < 10 or width < 100 or (scanline_y is not None and not 0 <= scanline_y < height):
        return None
    chroma = np.ptp(image.astype(np.float32), axis=2)
    scores = np.quantile(chroma[:, 4:32], 0.75, axis=1)
    reference = float(scores.max() if scanline_y is None else scores[scanline_y])
    rows = np.flatnonzero(scores > max(12, 0.5 * reference))
    if not len(rows):
        return None
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    if scanline_y is None:
        group = max(groups, key=lambda part: float(scores[part].sum()))
    else:
        group = next((part for part in groups if part[0] <= scanline_y <= part[-1]), None)
        if group is None:
            # Calibration is intentionally approximate. The expanded capture
            # can contain the real bar a few pixels above or below the saved
            # midpoint, so select the nearest plausible chromatic band.
            group = min(groups, key=lambda part: abs((part[0] + part[-1]) / 2 - scanline_y))
            distance = abs((group[0] + group[-1]) / 2 - scanline_y)
            if distance > max(4, 2 * (group[-1] - group[0])):
                return None
    top, bottom = int(group[0]), int(group[-1]) + 1
    thickness = bottom - top
    margin = max(2, thickness // 2 + 1)
    if thickness < 4 or top < margin or bottom > height - margin:
        return None
    return top, bottom


def _outside_support(image: np.ndarray, top: int, bottom: int, outer: int) -> float:
    """A damage cap cannot end the rectangle while slot/paint continues after it."""
    gray = image.astype(np.float32).mean(axis=2)
    color = np.median(np.ptp(image.astype(np.float32), axis=2)[top:bottom], axis=0)
    threshold = max(12, 0.5 * float(np.quantile(color[4:32], 0.75)))
    columns = np.flatnonzero(color[4:50] > threshold) + 4
    if len(columns) < 4:
        return 1
    band = gray[top:bottom]
    reference = np.median(band[:, columns], axis=1)
    shape = reference - reference.mean()
    centered = band - band.mean(axis=0)
    coefficient = (shape[:, None] * centered).sum(axis=0) / max(1, float((shape * shape).sum()))
    residual = np.sqrt(np.mean((centered - shape[:, None] * coefficient) ** 2, axis=0))
    outside = (gray[max(0, top - 3) : top - 1].mean(axis=0) + gray[bottom + 1 : bottom + 3].mean(axis=0)) / 2
    darkening = (outside - band.mean(axis=0)) / np.maximum(20, outside)
    supported = ((coefficient > 0.5) & (residual < 0.5 * max(10, float(np.std(reference))))) | (
        darkening > 0.22
    )
    after = supported[outer + 3 : outer + 3 + 2 * (bottom - top)]
    return float(after.mean()) if len(after) else 1


class MaterialModel:
    """Stateless ONNX inference, reusable by independent temporal trackers."""

    def __init__(self, model_dir: Path | None = None) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        root = Path(__file__).with_name("data") if model_dir is None else model_dir
        self._material = ort.InferenceSession(
            str(root / "material_v1.onnx"), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._cap = ort.InferenceSession(
            str(root / "cap_v1.onnx"), sess_options=options, providers=["CPUExecutionProvider"]
        )

    def estimate(self, image: np.ndarray) -> tuple[int, int] | None:
        features = material_features(image)
        if features is None:
            return None
        probabilities = self._material.run(["probabilities"], {"X": features})[0]
        log = np.log(np.clip(probabilities, 0.001, 0.999))
        usable = np.r_[0, np.cumsum(log[:, 0] - log[:, 2])]
        gray = np.r_[0, np.cumsum(log[:, 1] - log[:, 2])]
        # Maximize usable[0:U] + optional gray[U:T] + background[T:].
        # Suffix maxima solve all (U,T) pairs in linear time. No length prior.
        suffix = gray.copy()
        positions = np.arange(len(gray))
        for index in range(len(gray) - 2, -1, -1):
            if suffix[index + 1] > suffix[index]:
                suffix[index], positions[index] = suffix[index + 1], positions[index + 1]
        score = usable - gray + suffix
        score[:40], score[-20:] = -np.inf, -np.inf
        boundary = int(score.argmax())
        outer = int(positions[boundary])
        if outer >= len(features) - 20:
            return None
        band = cv2.resize(image, (image.shape[1], 24), interpolation=cv2.INTER_AREA).astype(np.float32)
        luminance = band[8:16].mean(axis=(0, 2))
        smooth = (np.roll(luminance, 1) + luminance + np.roll(luminance, -1)) / 3
        ridge = luminance - np.maximum(np.roll(smooth, 3), np.roll(smooth, -3))
        left, right = max(1, boundary - 4), min(len(luminance) - 1, boundary + 5)
        peak = left + int(ridge[left:right].argmax())
        if ridge[peak] <= 0:
            peak = boundary
        candidates = np.arange(max(0, peak - 2), min(len(features), peak + 3))
        cap = self._cap.run(["probabilities"], {"X": cap_features(features, candidates)})[0][:, 1]
        if float(cap.max()) <= 0.6:
            return None
        return int(candidates[cap.argmax()]), outer


def _normalized(
    image: np.ndarray, top: int, bottom: int, scanline_y: int | None, bar_height: int | None
) -> np.ndarray:
    # `scanline_y` selects the intended row band. Once selected, center the
    # material crop on that observed band; debug captures and JPEG scaling can
    # shift the rendered band relative to the original calibration midpoint.
    center = (top + bottom) // 2
    observed_height = bottom - top
    # A debug JPEG may be vertically resampled after capture. Use the observed
    # band only for such oversized diagnostic crops; production captures retain
    # the calibrated scale learned by the model.
    oversized_debug = image.shape[0] > 36 and observed_height > 1.25 * (bar_height or observed_height)
    calibrated_height = observed_height if bar_height is None or oversized_debug else bar_height
    height = 3 * calibrated_height
    # Crop a calibrated-height context window first. ``material_features``
    # performs the single canonical resize to 24 rows; resizing here as well
    # would blur production captures and change the texture scale seen by the
    # trained classifier.
    half = height / 2
    source_top = center - half
    source_height = max(1, int(np.ceil(height)))
    source_top_i = int(np.floor(source_top))
    source = np.empty((source_height, image.shape[1], image.shape[2]), dtype=image.dtype)
    for row in range(source_height):
        source_row = np.clip(source_top_i + row, 0, image.shape[0] - 1)
        source[row] = image[source_row]
    return source


def estimate_material_boundary(
    image: np.ndarray,
    *,
    scanline_y: int | None = None,
    bar_height: int | None = None,
    model: MaterialModel | None = None,
) -> MaterialBoundary | None:
    """Inspect current pixels only; callers may explicitly reuse a stateless model."""
    section = _section(image, scanline_y)
    if section is None:
        return None
    if bar_height is not None and bar_height < 4:
        return None
    top, bottom = section
    normalized = _normalized(image, top, bottom, scanline_y, bar_height)
    # Old offline crops include a few pixels before the cap. Production keeps
    # the calibrated left edge; normalize only an observable inset in old inputs.
    inset = int(image[top:bottom, :16].mean(axis=(0, 2)).argmax()) if scanline_y is None else 0
    if inset <= 3:
        inset = 0
    result = (model or MaterialModel()).estimate(normalized[:, inset:])
    if result is None:
        return MaterialBoundary(top, bottom, None, None)
    usable, outer = (coordinate + inset for coordinate in result)
    if _outside_support(image, top, bottom, outer) > 0.6:
        return MaterialBoundary(top, bottom, None, None)
    return MaterialBoundary(top, bottom, outer, usable)


class MaterialHpDetector:
    """Require current evidence and three agreeing observations in a five-call window."""

    def __init__(self, model: MaterialModel | None = None) -> None:
        self._model = model
        self.reset()

    def reset(self) -> None:
        self._shape: tuple[int, ...] | None = None
        self._scanline_y: int | None = None
        self._bar_height: int | None = None
        self._recent: deque[int | None] = deque(maxlen=5)

    def detect(
        self, image: np.ndarray, *, scanline_y: int | None = None, bar_height: int | None = None
    ) -> MaterialBoundary | None:
        if image.shape != self._shape or scanline_y != self._scanline_y or bar_height != self._bar_height:
            self.reset()
            self._shape, self._scanline_y = image.shape, scanline_y
            self._bar_height = bar_height
        self._recent.append(None)
        if _section(image, scanline_y) is None:
            self._recent.clear()
            return None
        if self._model is None:
            self._model = MaterialModel()
        result = estimate_material_boundary(
            image, scanline_y=scanline_y, bar_height=bar_height, model=self._model
        )
        if result is not None and result.usable is not None:
            self._recent[-1] = result.usable
            votes = [value for value in self._recent if value is not None and abs(value - result.usable) <= 3]
            if len(votes) >= 3 and max(votes) - min(votes) <= 3:
                return MaterialBoundary(result.top, result.bottom, result.outer, int(np.median(votes)))
            return MaterialBoundary(result.top, result.bottom, result.outer, None)
        return result
