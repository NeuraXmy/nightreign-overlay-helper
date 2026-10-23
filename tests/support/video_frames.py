"""Stream video fixtures or reuse lossless, content-addressed decoded BGR frames."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile

import cv2
import numpy as np

from tests.support.paths import PROJECT_ROOT


def decoded_video(path: Path, *, fps: float, frame_count: int, cache_dir: Path | None = None) -> np.ndarray:
    """Save every frame once, then memory-map it read-only on subsequent runs."""
    cache_dir = cache_dir or PROJECT_ROOT / ".tmp/decoded-video-frames"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    target = cache_dir / f"{digest}-{cv2.__version__}-{fps:g}-{frame_count}.npy"
    if target.is_file():
        frames = np.load(target, mmap_mode="r", allow_pickle=False)
        if frames.dtype != np.uint8 or frames.ndim != 4 or frames.shape[0] != frame_count:
            raise ValueError(f"Invalid decoded frame cache: {target}")
        return frames
    cache_dir.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=cache_dir, suffix=".npy", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        source = video_frames(path, fps=fps, frame_count=frame_count)
        try:
            first = next(source)
            frames = np.lib.format.open_memmap(
                temporary_path, mode="w+", dtype=np.uint8, shape=(frame_count, *first.shape)
            )
            try:
                frames[0] = first
                for index, bgr in enumerate(source, 1):
                    frames[index] = bgr
                frames.flush()
            finally:
                del frames
        finally:
            source.close()
        temporary_path.replace(target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return np.load(target, mmap_mode="r", allow_pickle=False)


def video_frames(
    path: Path, *, fps: float, frame_count: int, predecoded: bool = False
) -> Iterator[np.ndarray]:
    """Keep frame order, pixels and FPS identical for streaming and cached evaluation."""
    if predecoded:
        yield from decoded_video(path, fps=fps, frame_count=frame_count)
        return
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise RuntimeError(f"Cannot decode fixture: {path}")
        actual_fps = capture.get(cv2.CAP_PROP_FPS)
        if actual_fps != fps:
            raise AssertionError(f"Unexpected FPS: {actual_fps}; expected {fps}")
        count = 0
        while True:
            ok, bgr = capture.read()
            if not ok:
                break
            count += 1
            if count > frame_count:
                raise AssertionError(f"More than {frame_count} frames in {path}")
            yield bgr
        if count != frame_count:
            raise AssertionError(f"Decoded {count} frames; expected {frame_count}")
    finally:
        capture.release()
