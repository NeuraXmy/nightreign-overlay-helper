"""Typed publish/subscribe event bus.

Events are plain (preferably frozen) dataclasses; subscribers register for an event type and also receive
subclasses of it. Events published from worker threads are delivered on the bus' (GUI) thread.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any, TypeVar

from PyQt6.QtCore import QObject, pyqtSignal

from nightreign_overlay.core.log import get_logger

log = get_logger(__name__)

E = TypeVar("E")
Handler = Callable[[Any], None]


class Subscription:
    """Handle returned by :meth:`EventBus.subscribe`; call :meth:`cancel` to stop receiving events."""

    def __init__(self, bus: EventBus, event_type: type, handler: Handler) -> None:
        self._bus = bus
        self.event_type = event_type
        self.handler = handler
        self.active = True

    def cancel(self) -> None:
        if self.active:
            self.active = False
            self._bus._remove(self)


class EventBus(QObject):
    # AutoConnection: direct delivery when published from the bus thread, queued otherwise.
    _dispatch = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._subscriptions: defaultdict[type, list[Subscription]] = defaultdict(list)
        self._dispatch.connect(self._deliver)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> Subscription:
        subscription = Subscription(self, event_type, handler)
        self._subscriptions[event_type].append(subscription)
        return subscription

    def publish(self, event: object) -> None:
        self._dispatch.emit(event)

    def _remove(self, subscription: Subscription) -> None:
        subscriptions = self._subscriptions.get(subscription.event_type, [])
        if subscription in subscriptions:
            subscriptions.remove(subscription)

    def _deliver(self, event: object) -> None:
        for event_type in type(event).__mro__:
            for subscription in list(self._subscriptions.get(event_type, ())):
                if not subscription.active:
                    continue
                try:
                    subscription.handler(event)
                except Exception:
                    log.exception("Event handler %r failed for %r", subscription.handler, event)
