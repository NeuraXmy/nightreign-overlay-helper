from __future__ import annotations

from typing import Any

from nightreign_overlay.core.config import BoolOption, ConfigGroup, Option


def _is_binding(value: Any) -> bool:
    return isinstance(value, str) or (
        isinstance(value, dict)
        and set(value) == {"device", "keys"}
        and (value["device"] is None or value["device"] in ("keyboard", "mousebutton", "joystick"))
        and isinstance(value["keys"], list)
        and all(isinstance(key, str) for key in value["keys"])
    )


def _is_bindings(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(action, str) and _is_binding(binding) for action, binding in value.items()
    )


class InputConfig(ConfigGroup):
    enable_global_listener = BoolOption(True)
    bindings = Option[dict[str, Any]]({}, validator=_is_bindings)
