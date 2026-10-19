from __future__ import annotations

from collections.abc import Callable
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from PyQt6.QtWidgets import QApplication

from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin import (
    PLUGIN_KIND_DISPLAY_ORDER,
    Plugin,
    PluginKind,
    PluginManager,
    PluginManifest,
    PluginState,
    SettingsScope,
)
from nightreign_overlay.plugin import manager as manager_module

#: Lifecycle calls recorded by the fake plugins, e.g. ``("activate", "a")``.
Calls = list[tuple[str, str]]


def make_plugin(
    plugin_id: str, calls: Calls, *, fail_activate: bool = False, **manifest: Any
) -> type[Plugin]:
    class FakePlugin(Plugin):
        def on_load(self) -> None:
            calls.append(("load", self.id))

        def on_activate(self) -> None:
            calls.append(("activate", self.id))
            self.ctx.on_cleanup(lambda: calls.append(("cleanup", self.id)))
            if fail_activate:
                raise RuntimeError("activation failed")

        def on_deactivate(self) -> None:
            calls.append(("deactivate", self.id))

    FakePlugin.manifest = PluginManifest(id=plugin_id, **manifest)
    FakePlugin.__name__ = f"FakePlugin_{plugin_id}"
    return FakePlugin


@pytest.fixture
def calls() -> Calls:
    return []


@pytest.fixture
def make_manager(store: ConfigStore, qapp: QApplication) -> Callable[..., PluginManager]:
    def factory(*plugins: type[Plugin]) -> PluginManager:
        manager = PluginManager(store, Translator("zh_CN"), ServiceRegistry(), EventBus())
        for plugin_cls in plugins:
            manager.register(plugin_cls)
        manager.load_all()
        return manager

    return factory


def ids(manager: PluginManager) -> list[str]:
    return [record.id for record in manager.records()]


def test_order_follows_dependencies_then_kind(
    calls: Calls, make_manager: Callable[..., PluginManager]
) -> None:
    manager = make_manager(
        make_plugin("debug", calls, kind=PluginKind.DEBUG),
        make_plugin("feature", calls, requires=("capture",)),
        make_plugin("capture", calls, kind=PluginKind.INFRASTRUCTURE, optional=("hotkeys",)),
        make_plugin("hotkeys", calls, kind=PluginKind.INFRASTRUCTURE, order=200),
    )
    assert ids(manager) == ["hotkeys", "capture", "feature", "debug"]
    assert [c for c in calls if c[0] == "load"] == [("load", p) for p in ids(manager)]


def test_settings_scope_defaults_to_a_standalone_page() -> None:
    manifest = PluginManifest(id="feature")
    assert manifest.settings_scope == SettingsScope.PAGE
    assert PLUGIN_KIND_DISPLAY_ORDER == (PluginKind.FEATURE, PluginKind.INFRASTRUCTURE, PluginKind.DEBUG)


def test_default_enablement_follows_plugin_kind(
    calls: Calls, make_manager: Callable[..., PluginManager]
) -> None:
    manager = make_manager(
        make_plugin("feature", calls, kind=PluginKind.FEATURE),
        make_plugin("infrastructure", calls, kind=PluginKind.INFRASTRUCTURE),
        make_plugin("debug", calls, kind=PluginKind.DEBUG),
    )
    manager.start()

    assert manager.is_active("feature")
    assert manager.is_active("infrastructure")
    assert not manager.is_active("debug")


def test_managed_infrastructure_cannot_be_disabled(
    calls: Calls, make_manager: Callable[..., PluginManager]
) -> None:
    manager = make_manager(make_plugin("capture", calls, kind=PluginKind.INFRASTRUCTURE))
    manager.start()

    assert manager.is_active("capture")
    assert not manager.is_user_toggleable("capture")
    assert manager.set_enabled("capture", False) == []
    assert manager.is_active("capture")


def test_missing_requirement_makes_plugin_and_dependents_unavailable(
    calls: Calls, make_manager: Callable[..., PluginManager]
) -> None:
    manager = make_manager(
        make_plugin("a", calls, requires=("ghost",)),
        make_plugin("b", calls, requires=("a",)),
        make_plugin("c", calls),
    )
    a, b, c = (manager.get(p) for p in "abc")
    assert a and b and c
    assert (a.state, a.missing) == (PluginState.UNAVAILABLE, ("ghost",))
    assert (b.state, b.missing) == (PluginState.UNAVAILABLE, ())
    assert c.state == PluginState.INACTIVE
    assert ("load", "a") not in calls and ("load", "b") not in calls

    assert manager.set_enabled("b", True) == []
    assert b.state == PluginState.UNAVAILABLE


def test_required_cycle_is_unavailable(calls: Calls, make_manager: Callable[..., PluginManager]) -> None:
    manager = make_manager(
        make_plugin("a", calls, requires=("b",)),
        make_plugin("b", calls, requires=("a",)),
        make_plugin("c", calls, requires=("a",)),
    )
    a, b, c = (manager.get(p) for p in "abc")
    assert a and b and c
    assert a.circular and b.circular and not c.circular
    assert {a.state, b.state, c.state} == {PluginState.UNAVAILABLE}


def test_optional_cycle_is_broken(calls: Calls, make_manager: Callable[..., PluginManager]) -> None:
    manager = make_manager(
        make_plugin("a", calls, optional=("b",)),
        make_plugin("b", calls, requires=("a",)),
    )
    assert ids(manager) == ["a", "b"]
    assert all(record.state == PluginState.INACTIVE for record in manager.records())


def test_start_respects_enabled_flags(calls: Calls, make_manager: Callable[..., PluginManager]) -> None:
    manager = make_manager(make_plugin("on", calls), make_plugin("off", calls, default_enabled=False))
    manager.start()
    assert manager.is_active("on")
    assert not manager.is_active("off")


def test_enabling_cascades_to_requirements(
    calls: Calls, make_manager: Callable[..., PluginManager], store: ConfigStore
) -> None:
    manager = make_manager(
        make_plugin("base", calls, default_enabled=False),
        make_plugin("feature", calls, requires=("base",), default_enabled=False),
    )
    manager.start()
    assert manager.set_enabled("feature", True) == ["base"]
    assert manager.is_active("base") and manager.is_active("feature")
    assert calls.index(("activate", "base")) < calls.index(("activate", "feature"))

    calls.clear()
    assert manager.set_enabled("base", False) == ["feature"]
    assert not manager.is_active("base") and not manager.is_active("feature")
    # Dependents are stopped first; context cleanups run right after each deactivation.
    assert calls == [
        ("deactivate", "feature"),
        ("cleanup", "feature"),
        ("deactivate", "base"),
        ("cleanup", "base"),
    ]

    store.flush()
    reloaded = PluginManager(ConfigStore(store.path), Translator("zh_CN"), ServiceRegistry(), EventBus())
    reloaded.register(make_plugin("base", calls))
    assert reloaded.is_enabled("base") is False


def test_failed_activation_releases_context(calls: Calls, make_manager: Callable[..., PluginManager]) -> None:
    manager = make_manager(make_plugin("broken", calls, fail_activate=True))
    states: list[str] = []
    manager.stateChanged.connect(states.append)
    manager.start()

    record = manager.get("broken")
    assert record is not None
    assert record.state == PluginState.FAILED
    assert record.error == "activation failed"
    assert ("cleanup", "broken") in calls

    manager.set_enabled("broken", False)
    assert record.state == PluginState.INACTIVE
    assert states == ["broken", "broken"]


class Greeter:
    def greet(self) -> str:
        return "hello"


def test_context_resources_are_released_on_deactivate(store: ConfigStore, qapp: QApplication) -> None:
    received: list[object] = []

    class Provider(Plugin):
        manifest = PluginManifest(id="provider")

        def on_activate(self) -> None:
            self.ctx.provide(Greeter, Greeter())
            self.ctx.subscribe(str, received.append)

    services, events = ServiceRegistry(), EventBus()
    manager = PluginManager(store, Translator("zh_CN"), services, events)
    manager.register(Provider)
    manager.load_all()
    manager.start()
    assert services.require(Greeter).greet() == "hello"
    events.publish("ping")

    manager.shutdown()
    events.publish("pong")
    assert services.get(Greeter) is None
    assert received == ["ping"]


def test_duplicate_ids_are_rejected(calls: Calls, store: ConfigStore, qapp: QApplication) -> None:
    manager = PluginManager(store, Translator("zh_CN"), ServiceRegistry(), EventBus())
    manager.register(make_plugin("same", calls))
    with pytest.raises(ValueError):
        manager.register(make_plugin("same", calls))


def test_builtin_plugins_are_discovered(store: ConfigStore, qapp: QApplication) -> None:
    translator = Translator("en_US")
    manager = PluginManager(store, translator, ServiceRegistry(), EventBus())
    manager.discover()
    manager.load_all()
    record = manager.get("rain_timer")
    assert record is not None and record.state == PluginState.INACTIVE
    assert manager.get("overlay_test") is None
    assert manager.display_name("rain_timer") == "Rain Exposure Timer"
    assert record.plugin is not None and record.plugin.ctx.tutorial_file() is not None

    capture = manager.get("capture")
    hud = manager.get("hud")
    input_plugin = manager.get("input")
    region = manager.get("region")
    assert capture and capture.manifest.settings_scope == SettingsScope.GENERAL
    assert hud and hud.manifest.settings_scope == SettingsScope.GENERAL
    assert input_plugin and input_plugin.manifest.settings_scope == SettingsScope.HIDDEN
    assert region and region.manifest.settings_scope == SettingsScope.HIDDEN


@pytest.mark.parametrize("lazy", [False, True])
def test_discovery_continues_after_import_failure(store, qapp, monkeypatch, caplog, calls, lazy):
    package = ModuleType("test_plugins")
    package.__path__ = []
    broken = ModuleType("test_plugins.broken")
    healthy = ModuleType("test_plugins.healthy")
    healthy.PLUGIN = make_plugin("healthy", calls)

    def fail_export(name):
        raise OSError("Cannot decode image: maps/0.jpg")

    broken.__getattr__ = fail_export

    def import_module(name):
        if name == broken.__name__ and not lazy:
            raise OSError("Cannot decode image: maps/0.jpg")
        return {package.__name__: package, broken.__name__: broken, healthy.__name__: healthy}[name]

    monkeypatch.setattr(manager_module.importlib, "import_module", import_module)
    monkeypatch.setattr(
        manager_module.pkgutil,
        "iter_modules",
        lambda _: [SimpleNamespace(name=name, ispkg=True) for name in ("broken", "healthy")],
    )
    manager = PluginManager(store, Translator("zh_CN"), ServiceRegistry(), EventBus())
    manager.discover(package.__name__)

    assert manager.get("healthy") is not None
    assert "Failed to import plugin package test_plugins.broken" in caplog.text
    assert "Cannot decode image: maps/0.jpg" in caplog.text


@pytest.mark.parametrize("fail_constructor", [False, True])
def test_load_failure_releases_resources_and_enable_retries(store, qapp, fail_constructor):
    services, events = ServiceRegistry(), EventBus()
    received, cleaned = [], []
    attempts = []

    class Recoverable(Plugin):
        manifest = PluginManifest(id="recoverable")

        def __init__(self, ctx):
            super().__init__(ctx)
            if fail_constructor:
                self.initialize()

        def initialize(self):
            attempts.append(True)
            self.ctx.provide(Greeter, Greeter())
            self.ctx.subscribe(str, received.append)
            self.ctx.on_cleanup(lambda: cleaned.append(True))
            if len(attempts) == 1:
                raise OSError("temporarily unavailable")

        def on_load(self):
            if not fail_constructor:
                self.initialize()

    manager = PluginManager(store, Translator("zh_CN"), services, events)
    manager.register(Recoverable)
    manager.load_all()
    assert manager.get("recoverable").state == PluginState.FAILED
    assert services.get(Greeter) is None
    events.publish("stale")
    assert received == [] and cleaned == [True]
    manager.set_enabled("recoverable", False)
    manager.set_enabled("recoverable", True)
    assert manager.is_active("recoverable")
    assert services.get(Greeter) is not None
    events.publish("recovered")
    assert received == ["recovered"]
    manager.shutdown()
    assert cleaned == [True, True]
