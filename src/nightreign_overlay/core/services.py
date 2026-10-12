"""Service registry: the contract based way for plugins (and the core) to expose capabilities.

A service is keyed by its API type, normally a class defined in a provider plugin's ``api.py``. Consumers only
import that module, never the provider's implementation.
"""

from __future__ import annotations

from typing import Any, TypeVar, cast

from PyQt6.QtCore import QObject, pyqtSignal

T = TypeVar("T")

CORE_OWNER = "core"


class ServiceRegistry(QObject):
    #: Emitted with the API type whenever a service is registered or unregistered.
    serviceChanged = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services: dict[type, tuple[Any, str]] = {}

    def register(self, api: type[T], implementation: T, owner: str = CORE_OWNER) -> None:
        if api in self._services:
            raise ValueError(f"service {api.__name__} is already provided by {self._services[api][1]!r}")
        self._services[api] = (implementation, owner)
        self.serviceChanged.emit(api)

    def unregister(self, api: type) -> None:
        if self._services.pop(api, None) is not None:
            self.serviceChanged.emit(api)

    def unregister_owner(self, owner: str) -> None:
        for api in [api for api, (_, o) in self._services.items() if o == owner]:
            self.unregister(api)

    def get(self, api: type[T]) -> T | None:
        entry = self._services.get(api)
        return cast(T, entry[0]) if entry else None

    def require(self, api: type[T]) -> T:
        service = self.get(api)
        if service is None:
            raise LookupError(f"service {api.__name__} is not available")
        return service
