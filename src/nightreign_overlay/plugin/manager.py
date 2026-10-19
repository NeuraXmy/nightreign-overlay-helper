"""Plugin discovery, dependency resolution and lifecycle management."""

from __future__ import annotations

import heapq
import importlib
import pkgutil
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from nightreign_overlay.core.config import ConfigGroup, ConfigStore, Option
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.log import get_logger
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.base import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugin.context import PluginContext

log = get_logger(__name__)

BUILTIN_PLUGIN_PACKAGE = "nightreign_overlay.plugins"
#: Every plugin package exposes its plugin class under this module attribute.
PLUGIN_ATTRIBUTE = "PLUGIN"

_KIND_RANK = {PluginKind.INFRASTRUCTURE: 0, PluginKind.FEATURE: 1, PluginKind.DEBUG: 2}


class PluginState(StrEnum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    #: A required plugin is missing or part of a dependency cycle; the plugin can never be enabled.
    UNAVAILABLE = "unavailable"
    #: Loading or activation raised an exception.
    FAILED = "failed"


@dataclass
class PluginRecord:
    cls: type[Plugin]
    plugin: Plugin | None = None
    state: PluginState = PluginState.INACTIVE
    missing: tuple[str, ...] = ()
    circular: bool = False
    error: str = ""

    @property
    def manifest(self) -> PluginManifest:
        return self.cls.manifest

    @property
    def id(self) -> str:
        return self.cls.manifest.id


def _is_enabled_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, bool) for k, v in value.items()
    )


class PluginManagerConfig(ConfigGroup):
    enabled = Option[dict[str, bool]]({}, validator=_is_enabled_map)


class PluginManager(QObject):
    #: Emitted with the plugin id whenever its state changes.
    stateChanged = pyqtSignal(str)

    def __init__(
        self,
        store: ConfigStore,
        translator: Translator,
        services: ServiceRegistry,
        events: EventBus,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._translator = translator
        self._services = services
        self._events = events
        self._config = store.bind(PluginManagerConfig, "plugin_manager")
        self._records: dict[str, PluginRecord] = {}
        self._order: list[str] = []

    # -- registration -------------------------------------------------------------------------

    def discover(self, package_name: str = BUILTIN_PLUGIN_PACKAGE) -> None:
        """Import every sub-package of ``package_name`` and register its ``PLUGIN`` class."""
        package = importlib.import_module(package_name)
        for module_info in pkgutil.iter_modules(package.__path__):
            if not module_info.ispkg:
                continue
            module_name = f"{package_name}.{module_info.name}"
            try:
                module = importlib.import_module(module_name)
                # Lazy package exports can import the implementation in __getattr__.
                plugin_cls = getattr(module, PLUGIN_ATTRIBUTE, None)
            except Exception:
                log.exception("Failed to import plugin package %s", module_name)
                continue
            if plugin_cls is None:
                log.warning("Plugin package %s does not define %s", module_name, PLUGIN_ATTRIBUTE)
                continue
            self.register(plugin_cls)

    def register(self, plugin_cls: type[Plugin]) -> None:
        plugin_id = plugin_cls.manifest.id
        if plugin_id in self._records:
            raise ValueError(f"duplicate plugin id {plugin_id!r}")
        self._records[plugin_id] = PluginRecord(plugin_cls)

    # -- lifecycle ----------------------------------------------------------------------------

    def load_all(self) -> None:
        """Resolve the dependency order and call ``on_load`` on every available plugin."""
        self._order = self._resolve_order()
        for plugin_id in self._order:
            record = self._records[plugin_id]
            root_dir = _plugin_root(record.cls)
            # Translations are loaded even for unavailable plugins so the UI can name them.
            self._translator.load_dir(plugin_id, root_dir / "i18n")
            if record.state == PluginState.UNAVAILABLE:
                continue
            self._load_plugin(record)

    def _load_plugin(self, record: PluginRecord) -> bool:
        ctx = PluginContext(
            record.id,
            _plugin_root(record.cls),
            self._store,
            self._translator,
            self._services,
            self._events,
        )
        try:
            record.plugin = record.cls(ctx)
            record.plugin.on_load()
        except Exception as e:
            log.exception("Failed to load plugin %s", record.id)
            ctx.release()
            record.plugin = None
            record.state = PluginState.FAILED
            record.error = str(e)
            self.stateChanged.emit(record.id)
            return False
        record.state = PluginState.INACTIVE
        record.error = ""
        return True

    def start(self) -> None:
        """Activate all enabled plugins in dependency order."""
        for plugin_id in self._order:
            if self.is_enabled(plugin_id) and self._records[plugin_id].state == PluginState.INACTIVE:
                self._activate(plugin_id)

    def shutdown(self) -> None:
        for plugin_id in reversed(self._order):
            if self._records[plugin_id].state == PluginState.ACTIVE:
                self._deactivate(plugin_id)

    # -- queries ------------------------------------------------------------------------------

    @property
    def config_store(self) -> ConfigStore:
        """The application-wide store used for complete settings import and export."""
        return self._store

    def records(self) -> list[PluginRecord]:
        """All plugins: resolved ones in activation order, followed by unavailable ones."""
        return [self._records[plugin_id] for plugin_id in self._order]

    def get(self, plugin_id: str) -> PluginRecord | None:
        return self._records.get(plugin_id)

    def display_name(self, plugin_id: str) -> str:
        name = self._translator.tr(plugin_id, "plugin.name")
        return plugin_id if name == "plugin.name" else name

    def description(self, plugin_id: str) -> str:
        text = self._translator.tr(plugin_id, "plugin.description")
        return "" if text == "plugin.description" else text

    def is_enabled(self, plugin_id: str) -> bool:
        record = self._records[plugin_id]
        if record.manifest.kind == PluginKind.INFRASTRUCTURE:
            return True
        return self._config.enabled.value.get(plugin_id, record.manifest.initial_enabled)

    def is_user_toggleable(self, plugin_id: str) -> bool:
        """Whether a user may enable or disable this plugin from the interface."""
        return self._records[plugin_id].manifest.kind != PluginKind.INFRASTRUCTURE

    def is_active(self, plugin_id: str) -> bool:
        record = self._records.get(plugin_id)
        return record is not None and record.state == PluginState.ACTIVE

    def requirements_of(self, plugin_id: str) -> list[str]:
        """``plugin_id`` and all plugins it transitively requires, in activation order."""
        closure: set[str] = set()
        stack = [plugin_id]
        while stack:
            current = stack.pop()
            if current in closure or current not in self._records:
                continue
            closure.add(current)
            stack.extend(self._records[current].manifest.requires)
        return [p for p in self._order if p in closure]

    def dependents_of(self, plugin_id: str) -> list[str]:
        """``plugin_id`` and all plugins that transitively require it, in deactivation order."""
        closure = {plugin_id}
        changed = True
        while changed:
            changed = False
            for record in self._records.values():
                if record.id not in closure and closure.intersection(record.manifest.requires):
                    closure.add(record.id)
                    changed = True
        return [p for p in reversed(self._order) if p in closure]

    # -- user actions -------------------------------------------------------------------------

    def set_enabled(self, plugin_id: str, enabled: bool) -> list[str]:
        """Enable / disable a user-controllable plugin together with its requirements / dependents.

        Returns the ids of *other* plugins whose enabled state changed as a side effect.
        Infrastructure plugins are always managed by the application and cannot be disabled through this
        user-action entrypoint.
        """
        if not self.is_user_toggleable(plugin_id):
            log.info("Ignored user toggle for managed infrastructure plugin %s", plugin_id)
            return []
        chain = self.requirements_of(plugin_id) if enabled else self.dependents_of(plugin_id)
        if enabled and any(self._records[p].state == PluginState.UNAVAILABLE for p in chain):
            log.warning("Cannot enable %s: a requirement is unavailable", plugin_id)
            return []

        affected = [p for p in chain if p != plugin_id and self.is_enabled(p) != enabled]
        self._config.enabled.set({**self._config.enabled.value, **dict.fromkeys(chain, enabled)})

        for p in chain:
            state = self._records[p].state
            if enabled and state in (PluginState.INACTIVE, PluginState.FAILED):
                self._activate(p)
            elif not enabled and state == PluginState.ACTIVE:
                self._deactivate(p)
            elif not enabled and state == PluginState.FAILED:
                self._records[p].state = PluginState.INACTIVE
                self.stateChanged.emit(p)
        return affected

    # -- internals ----------------------------------------------------------------------------

    def _activate(self, plugin_id: str) -> None:
        record = self._records[plugin_id]
        if record.plugin is None and not self._load_plugin(record):
            return
        inactive = [p for p in record.manifest.requires if not self.is_active(p)]
        if inactive:
            log.warning("Plugin %s not activated, requirements inactive: %s", plugin_id, inactive)
            return
        try:
            record.plugin.on_activate()
        except Exception as e:
            log.exception("Failed to activate plugin %s", plugin_id)
            record.plugin.ctx.release()
            record.state = PluginState.FAILED
            record.error = str(e)
        else:
            record.state = PluginState.ACTIVE
            record.error = ""
            log.info("Plugin %s activated", plugin_id)
        self.stateChanged.emit(plugin_id)

    def _deactivate(self, plugin_id: str) -> None:
        record = self._records[plugin_id]
        assert record.plugin is not None
        try:
            record.plugin.on_deactivate()
        except Exception:
            log.exception("Error while deactivating plugin %s", plugin_id)
        finally:
            record.plugin.ctx.release()
            record.state = PluginState.INACTIVE
            log.info("Plugin %s deactivated", plugin_id)
        self.stateChanged.emit(plugin_id)

    def _resolve_order(self) -> list[str]:
        """Topologically sort plugins; mark those with missing or circular requirements unavailable."""
        records = self._records
        for record in records.values():
            record.missing = tuple(r for r in record.manifest.requires if r not in records)

        def priority(plugin_id: str) -> tuple[int, int, str]:
            manifest = records[plugin_id].manifest
            return _KIND_RANK[manifest.kind], manifest.order, plugin_id

        dependencies = {
            pid: {d for d in (*r.manifest.requires, *r.manifest.optional) if d in records}
            for pid, r in records.items()
        }
        required = {pid: {d for d in r.manifest.requires if d in records} for pid, r in records.items()}
        remaining = {pid: len(deps) for pid, deps in dependencies.items()}
        heap = [priority(pid) for pid, count in remaining.items() if count == 0]
        heapq.heapify(heap)
        order: list[str] = []
        placed: set[str] = set()
        while True:
            while heap:
                plugin_id = heapq.heappop(heap)[2]
                if plugin_id in placed:
                    continue
                order.append(plugin_id)
                placed.add(plugin_id)
                for other, deps in dependencies.items():
                    if plugin_id in deps and other not in placed:
                        remaining[other] -= 1
                        if remaining[other] == 0:
                            heapq.heappush(heap, priority(other))
            # A cycle that only exists through optional dependencies is broken by placing a plugin whose
            # required dependencies are all satisfied; optional ones never make a plugin unavailable.
            candidates = [pid for pid in records if pid not in placed and required[pid] <= placed]
            if not candidates:
                break
            heapq.heappush(heap, priority(min(candidates, key=priority)))

        cyclic = sorted((pid for pid in records if pid not in placed), key=priority)
        for plugin_id in cyclic:
            # Leftovers either sit on a cycle of required dependencies or merely require something that does.
            records[plugin_id].circular = _reaches(plugin_id, plugin_id, required)
        order.extend(cyclic)

        # Unavailability propagates to everything that (transitively) requires an unavailable plugin.
        unavailable = {pid for pid, r in records.items() if r.missing or r.circular}
        changed = True
        while changed:
            changed = False
            for plugin_id, deps in required.items():
                if plugin_id not in unavailable and deps & unavailable:
                    unavailable.add(plugin_id)
                    changed = True
        for plugin_id in order:
            if plugin_id in unavailable:
                record = records[plugin_id]
                record.state = PluginState.UNAVAILABLE
                log.warning(
                    "Plugin %s unavailable (missing=%s, circular=%s)",
                    plugin_id,
                    record.missing,
                    record.circular,
                )
        return order


def _reaches(start: str, target: str, edges: dict[str, set[str]]) -> bool:
    """Whether ``target`` is reachable from ``start`` by following at least one edge."""
    seen: set[str] = set()
    stack = list(edges.get(start, ()))
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(edges.get(node, ()))
    return False


def _plugin_root(plugin_cls: type[Plugin]) -> Path:
    """Directory of the package that defines ``plugin_cls`` (holds its i18n / tutorial files)."""
    module = sys.modules[plugin_cls.__module__]
    assert module.__file__ is not None
    return Path(module.__file__).resolve().parent
