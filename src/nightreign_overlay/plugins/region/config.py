from __future__ import annotations

from typing import Any

from nightreign_overlay.core.config import ConfigGroup, Option


def is_valid_region(rect: Any) -> bool:
    """Validate positive device-pixel bounds representable by QRect, including its edges."""
    if not isinstance(rect, list) or len(rect) != 4:
        return False
    if any(isinstance(value, bool) or not isinstance(value, int) for value in rect):
        return False
    x, y, width, height = rect
    minimum, maximum = -(2**31), 2**31 - 1
    return (
        width > 0
        and height > 0
        and all(minimum <= value <= maximum for value in rect)
        and minimum <= x + width - 1 <= maximum
        and minimum <= y + height - 1 <= maximum
    )


def _is_regions(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and is_valid_region(rect) for key, rect in value.items()
    )


class RegionConfig(ConfigGroup):
    regions = Option[dict[str, list[int]]]({}, validator=_is_regions)
