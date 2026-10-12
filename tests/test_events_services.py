from __future__ import annotations

import threading
from dataclasses import dataclass

import pytest
from PyQt6.QtWidgets import QApplication

from conftest import process_events
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.services import ServiceRegistry


@dataclass(frozen=True)
class BaseEvent:
    value: int


@dataclass(frozen=True)
class DerivedEvent(BaseEvent):
    pass


def test_subscribers_receive_events_and_subclasses(qapp: QApplication) -> None:
    bus = EventBus()
    base: list[BaseEvent] = []
    derived: list[DerivedEvent] = []
    bus.subscribe(BaseEvent, base.append)
    bus.subscribe(DerivedEvent, derived.append)

    bus.publish(BaseEvent(1))
    bus.publish(DerivedEvent(2))
    assert [e.value for e in base] == [1, 2]
    assert [e.value for e in derived] == [2]


def test_cancelled_subscription_stops_delivery(qapp: QApplication) -> None:
    bus = EventBus()
    received: list[BaseEvent] = []
    subscription = bus.subscribe(BaseEvent, received.append)
    subscription.cancel()
    subscription.cancel()
    bus.publish(BaseEvent(1))
    assert received == []


def test_failing_handler_does_not_block_others(qapp: QApplication) -> None:
    bus = EventBus()
    received: list[BaseEvent] = []

    def broken(_event: BaseEvent) -> None:
        raise RuntimeError("boom")

    bus.subscribe(BaseEvent, broken)
    bus.subscribe(BaseEvent, received.append)
    bus.publish(BaseEvent(1))
    assert len(received) == 1


def test_events_from_worker_threads_are_delivered_on_the_gui_thread(qapp: QApplication) -> None:
    bus = EventBus()
    threads: list[threading.Thread] = []
    bus.subscribe(BaseEvent, lambda _e: threads.append(threading.current_thread()))

    worker = threading.Thread(target=lambda: bus.publish(BaseEvent(1)))
    worker.start()
    worker.join()
    assert threads == []  # queued, not delivered on the worker
    process_events()
    assert threads == [threading.main_thread()]


class Api:
    pass


class OtherApi:
    pass


def test_service_registry(qapp: QApplication) -> None:
    registry = ServiceRegistry()
    changes: list[type] = []
    registry.serviceChanged.connect(changes.append)

    impl = Api()
    registry.register(Api, impl, owner="plugin_a")
    registry.register(OtherApi, OtherApi(), owner="plugin_b")
    assert registry.require(Api) is impl
    with pytest.raises(ValueError):
        registry.register(Api, Api())

    registry.unregister_owner("plugin_a")
    assert registry.get(Api) is None
    assert registry.get(OtherApi) is not None
    with pytest.raises(LookupError):
        registry.require(Api)
    assert changes == [Api, OtherApi, Api]
