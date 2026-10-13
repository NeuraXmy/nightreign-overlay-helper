"""Public map recognition status, used by the circle timer's legacy readiness suffix."""

from __future__ import annotations


class MapRecognitionApi:
    """Read readiness without depending on map detector or overlay internals."""

    def ready(self) -> bool:
        raise NotImplementedError
