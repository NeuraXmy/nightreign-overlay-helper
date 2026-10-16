"""Temporal map gating, including real opening/closing frames with false full-map positives."""

from __future__ import annotations

import numpy as np
import pytest

from nightreign_overlay.plugins.map_detect.stability import MapStability, map_stability_sample
from tests.support.paths import MAP_CAPTURE_DIR


def _sample(value=80):
    return np.full((96, 96), value, dtype=np.uint8)


def test_requires_capture_duration_and_multiple_observations():
    gate = MapStability()
    sample = _sample()
    assert not gate.observe(sample, 100.0, True)
    assert not gate.observe(sample, 100.25, True)
    assert not gate.observe(sample, 100.5, True)
    assert gate.observe(sample, 100.75, True)

    gate.reset()
    assert not gate.observe(sample, 100.0, True)
    assert not gate.observe(sample, 102.0, True)
    assert gate.observe(sample, 104.0, True)


def test_change_threshold_and_stable_duration_are_configurable():
    gate = MapStability()
    assert not gate.observe(_sample(80), 0.0, True, change_threshold=3.0, stable_seconds=0.5)
    assert not gate.observe(_sample(84), 0.25, True, change_threshold=3.0, stable_seconds=0.5)
    assert not gate.observe(_sample(84), 0.5, True, change_threshold=3.0, stable_seconds=0.5)
    assert gate.observe(_sample(84), 0.75, True, change_threshold=3.0, stable_seconds=0.5)

    gate.reset()
    assert not gate.observe(_sample(), 1.0, True, stable_seconds=1.0)
    assert not gate.observe(_sample(), 1.5, True, stable_seconds=1.0)
    assert gate.observe(_sample(), 2.0, True, stable_seconds=1.0)


def test_changing_settings_discards_partial_stability_window():
    gate = MapStability()
    assert not gate.observe(_sample(), 0.0, True, stable_seconds=0.5)
    assert not gate.observe(_sample(), 0.25, True, stable_seconds=0.5)
    assert not gate.observe(_sample(), 0.5, True, stable_seconds=0.75)
    assert not gate.observe(_sample(), 0.75, True, stable_seconds=0.75)
    assert not gate.observe(_sample(), 1.0, True, stable_seconds=0.75)
    assert gate.observe(_sample(), 1.25, True, stable_seconds=0.75)


def test_full_map_failure_and_explicit_reset_discard_history():
    gate = MapStability()
    for timestamp in (0.0, 0.25, 0.5):
        assert not gate.observe(_sample(), timestamp, True)
    assert not gate.observe(None, 0.75, False)
    for timestamp in (1.0, 1.25, 1.5):
        assert not gate.observe(_sample(), timestamp, True)
    assert gate.observe(_sample(), 1.75, True)
    gate.reset()
    assert not gate.observe(_sample(), 2.0, True)


@pytest.mark.parametrize("timestamp", [0.5, 0.25, float("nan"), float("inf"), 4.0])
def test_invalid_timestamps_or_long_capture_gaps_cannot_complete_a_window(timestamp):
    gate = MapStability()
    for previous in (0.0, 0.25, 0.5):
        assert not gate.observe(_sample(), previous, True)
    assert not gate.observe(_sample(), timestamp, True)
    assert not gate.observe(_sample(), 4.25, True)


def test_slow_cumulative_fades_restart_the_window():
    gate = MapStability()
    # Each individual change is below the threshold, but the window's anchor
    # keeps a long, gradual fade from looking stable.
    for index in range(20):
        assert not gate.observe(_sample(80 + index), index * 0.1, True)
    for timestamp in (2.0, 2.2, 2.4):
        assert not gate.observe(_sample(120), timestamp, True)
    assert gate.observe(_sample(120), 2.8, True)


def test_closing_just_before_the_window_completes_does_not_pass():
    gate = MapStability()
    for timestamp in (0.0, 0.25, 0.5):
        assert not gate.observe(_sample(), timestamp, True)
    assert not gate.observe(_sample(70), 0.75, True)
    assert not gate.observe(_sample(60), 1.0, True)
    assert not gate.observe(None, 1.25, False)


def test_local_markers_and_small_compression_noise_do_not_prevent_recognition():
    gate = MapStability()
    random = np.random.default_rng(42)
    for index, timestamp in enumerate((0.0, 0.25, 0.5, 0.75)):
        sample = _sample() + random.integers(0, 2, (96, 96), dtype=np.uint8)
        sample[index * 12 : index * 12 + 10, 20:30] = 255
        assert gate.observe(sample, timestamp, True) == (index == 3)


def test_sample_ignores_outer_ui_but_preserves_absolute_fade_brightness():
    original = np.full((240, 240, 3), 120, dtype=np.uint8)
    border = original.copy()
    border[:24] = border[-24:] = border[:, :24] = border[:, -24:] = 0
    np.testing.assert_array_equal(map_stability_sample(original), map_stability_sample(border))
    assert float(map_stability_sample(original // 2).mean()) == 60
    assert float(map_stability_sample(original).mean()) == 120


@pytest.fixture(scope="module")
def transition_video():
    with np.load(MAP_CAPTURE_DIR / "transitions/map_open_close.npz", allow_pickle=False) as data:
        return {name: data[name] for name in ("samples", "captured_at", "full_map")}


@pytest.mark.parametrize("interval", [1 / 30, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0])
def test_video_every_request_start_and_sampling_phase_rejects_fades(transition_video, interval):
    samples = transition_video["samples"]
    timestamps = transition_video["captured_at"]
    full_map = transition_video["full_map"]
    assert samples.shape == (235, 96, 96)
    # Independently inspected safe interval: 2.4s through 5.7s. The circle
    # detector already accepts opening frame 62 and closing frame 174.
    assert full_map[62] and full_map[174]
    admitted = []
    for start in range(len(samples)):
        gate = MapStability()
        # The first frame is PREPARE's clear operation, excluded from history.
        next_at = timestamps[start] + interval
        for index in range(start + 1, len(samples)):
            if timestamps[index] + 1e-9 < next_at:
                continue
            next_at += interval
            if gate.observe(samples[index], float(timestamps[index]), bool(full_map[index])):
                assert 72 <= index <= 171, (start, interval, index)
                admitted.append(index)
                break
    # A gate which rejects everything is not a fix. Normal capture intervals
    # must still recognize the fully open map within this short recording.
    if interval <= 0.5:
        assert admitted
