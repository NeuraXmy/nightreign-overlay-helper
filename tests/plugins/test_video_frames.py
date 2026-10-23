"""Decoded fixture caches retain pixels and invalidate when the source changes."""

import cv2
import numpy as np
import pytest

from tests.support import video_frames


def _write_video(path, offset=0):
    frames = np.random.default_rng(offset).integers(0, 256, (4, 12, 16, 3), dtype=np.uint8)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"FFV1"), 10, (16, 12))
    assert writer.isOpened()
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()
    return frames


def test_saved_frames_are_lossless_read_only_reused_and_invalidated(tmp_path, monkeypatch):
    path = tmp_path / "source.mkv"
    expected = _write_video(path)
    cache = tmp_path / "cache"
    options = {"fps": 10, "frame_count": 4, "cache_dir": cache}
    frames = video_frames.decoded_video(path, **options)
    assert np.array_equal(frames, expected)
    assert not frames.flags.writeable
    with monkeypatch.context() as patch:

        def no_decoding(*args):
            pytest.fail("An unchanged video should reuse saved frames")

        patch.setattr(video_frames.cv2, "VideoCapture", no_decoding)
        assert np.array_equal(video_frames.decoded_video(path, **options), expected)
    changed = _write_video(path, offset=1)
    assert np.array_equal(video_frames.decoded_video(path, **options), changed)
    assert len(list(cache.glob("*.npy"))) == 2


@pytest.mark.parametrize("fps,frame_count", [(20, 4), (10, 3), (10, 5)])
def test_invalid_video_metadata_does_not_leave_a_cache(tmp_path, fps, frame_count):
    path = tmp_path / "source.mkv"
    _write_video(path)
    cache = tmp_path / "cache"
    with pytest.raises(AssertionError):
        video_frames.decoded_video(path, fps=fps, frame_count=frame_count, cache_dir=cache)
    assert not list(cache.iterdir())
