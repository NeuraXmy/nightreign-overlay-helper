"""Per plugin facade over the core services.

Everything a plugin registers through its context is tracked and released when the plugin is deactivated,
so plugins can be toggled at runtime without leaking subscriptions or services.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from nightreign_overlay.core.config import ConfigGroup, ConfigStore
from nightreign_overlay.core.events import EventBus, Subscription
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.log import get_logger
from nightreign_overlay.core.services import ServiceRegistry

T = TypeVar("T")
E = TypeVar("E")
G = TypeVar("G", bound=ConfigGroup)


class PluginContext:
    def __init__(
        self,
        plugin_id: str,
        root_dir: Path,
        store: ConfigStore,
        translator: Translator,
        services: ServiceRegistry,
        events: EventBus,
    ) -> None:
        self.plugin_id = plugin_id
        self.root_dir = root_dir
        self.services = services
        self.log: logging.Logger = get_logger(f"nightreign_overlay.plugins.{plugin_id}")
        self._store = store
        self._translator = translator
        self._events = events
        self._subscriptions: list[Subscription] = []
        self._cleanups: list[Callable[[], None]] = []

    # -- configuration / resources ------------------------------------------------------------

    def config(self, group_cls: type[G], section: str | None = None) -> G:
        """Bind a config group under ``plugins.<id>`` (or ``plugins.<id>.<section>``)."""
        namespace = f"plugins.{self.plugin_id}" + (f".{section}" if section else "")
        return self._store.bind(group_cls, namespace)

    def tr(self, key: str, **kwargs: Any) -> str:
        return self._translator.tr(self.plugin_id, key, **kwargs)

    def resource(self, *parts: str) -> Path:
        return self.root_dir.joinpath(*parts)

    def tutorial_file(self) -> Path | None:
        return self._translator.localized_file(self.root_dir / "tutorial", ".md")

    # -- runtime resources (released on deactivate) ---------------------------------------------

    def provide(self, api: type[T], implementation: T) -> None:
        self.services.register(api, implementation, owner=self.plugin_id)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> Subscription:
        subscription = self._events.subscribe(event_type, handler)
        self._subscriptions.append(subscription)
        return subscription

    def publish(self, event: object) -> None:
        self._events.publish(event)

    def on_cleanup(self, callback: Callable[[], None]) -> None:
        """Run ``callback`` after the plugin is deactivated (in reverse registration order)."""
        self._cleanups.append(callback)

    def release(self) -> None:
        """Release everything registered since activation. Called by the plugin manager."""
        for subscription in self._subscriptions:
            subscription.cancel()
        self._subscriptions.clear()
        self.services.unregister_owner(self.plugin_id)
        while self._cleanups:
            callback = self._cleanups.pop()
            try:
                callback()
            except Exception:
                self.log.exception("Cleanup callback failed")
