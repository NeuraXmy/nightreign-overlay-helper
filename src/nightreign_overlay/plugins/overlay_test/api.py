"""Service contract offered by the overlay test plugin.

Other plugins may import this module (and only this module) and look the service up with
``ctx.services.get(OverlayTestApi)``. This is the pattern every plugin-to-plugin dependency follows.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class OverlayTestApi(ABC):
    @abstractmethod
    def restart_countdown(self) -> None:
        """Restart the demo countdown from the full cycle length."""
