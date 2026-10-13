"""Map recognition and detailed map/crystal information."""

from typing import Any

__all__ = ["PLUGIN"]


def __getattr__(name: str) -> Any:
    """Load the plugin only when discovered, keeping public API imports lightweight."""
    if name == "PLUGIN":
        from nightreign_overlay.plugins.map_detect.plugin import MapDetectPlugin

        return MapDetectPlugin
    raise AttributeError(name)
