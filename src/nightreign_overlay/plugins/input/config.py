from __future__ import annotations

from typing import Any

from nightreign_overlay.core.config import BoolOption, ConfigGroup, Option


def _is_bindings(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(combo, str) for key, combo in value.items()
    )


class InputConfig(ConfigGroup):
    enable_global_listener = BoolOption(True)
    bindings = Option[dict[str, str]]({}, validator=_is_bindings)
