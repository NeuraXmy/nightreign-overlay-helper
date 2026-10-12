from __future__ import annotations

from typing import Any

from nightreign_overlay.core.config import ConfigGroup, Option


def _is_regions(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and isinstance(rect, list)
        and len(rect) == 4
        and all(isinstance(component, int) and not isinstance(component, bool) for component in rect)
        for key, rect in value.items()
    )


class RegionConfig(ConfigGroup):
    regions = Option[dict[str, list[int]]]({}, validator=_is_regions)
