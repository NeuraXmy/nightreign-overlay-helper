"""Shared warning and failure thresholds for HP refusal rates and consecutive durations."""

import warnings


def assert_rejection_ratio(ratio: float, *, context: str) -> None:
    """Accept up to 50% rejection, reporting rates above 20% as warnings."""
    assert ratio <= 0.5, f"{context}: rejection ratio {ratio:.2%} exceeds failure limit 50%"
    if ratio > 0.2:
        warnings.warn(
            f"{context}: rejection ratio {ratio:.2%} exceeds warning threshold 20% (failure limit 50%)",
            UserWarning,
            stacklevel=2,
        )


def assert_rejection_duration(seconds: float, *, context: str) -> None:
    """Accept up to 5s of consecutive rejection, reporting durations above 2s."""
    assert seconds <= 5, f"{context}: consecutive rejection {seconds:.2f}s exceeds failure limit 5s"
    if seconds > 2:
        warnings.warn(
            f"{context}: consecutive rejection {seconds:.2f}s "
            "exceeds warning threshold 2s (failure limit 5s)",
            UserWarning,
            stacklevel=2,
        )
