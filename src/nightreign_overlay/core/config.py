"""Declarative, observable configuration persisted to a single YAML file.

Usage::

    class MyConfig(ConfigGroup):
        enabled = BoolOption(True)
        opacity = RangeOption(90, 10, 100)
        mode = ChoiceOption("auto", ("auto", "manual"))

    cfg = store.bind(MyConfig, "plugins.my_plugin")
    cfg.opacity.value            # -> 90
    cfg.opacity.set(80)          # validated, persisted (debounced) and ``valueChanged`` is emitted
    cfg.opacity.valueChanged.connect(...)

Items must be modified from the GUI thread only.
"""

from __future__ import annotations

import copy
import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Generic, TypeVar, overload

import yaml
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from nightreign_overlay.core.log import get_logger

log = get_logger(__name__)

T = TypeVar("T")
G = TypeVar("G", bound="ConfigGroup")


# ---------------------------------------------------------------------------
# Options: immutable descriptions of a value (default + validation)
# ---------------------------------------------------------------------------


class Option(Generic[T]):
    """Describes one config value. Declare as a class attribute of a :class:`ConfigGroup`."""

    def __init__(self, default: T, *, validator: Callable[[Any], bool] | None = None) -> None:
        self.default = default
        self.name = ""
        self._validator = validator

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @overload
    def __get__(self, group: None, owner: type) -> Option[T]: ...
    @overload
    def __get__(self, group: ConfigGroup, owner: type) -> ConfigItem[T]: ...
    def __get__(self, group: ConfigGroup | None, owner: type) -> Option[T] | ConfigItem[T]:
        if group is None:
            return self
        return group.item(self.name)

    def normalize(self, raw: Any) -> T:
        """Return the canonical form of ``raw`` or raise :class:`ValueError` if it is not acceptable."""
        if self._validator is not None and not self._validator(raw):
            raise ValueError(f"invalid value for {self.name!r}: {raw!r}")
        return copy.deepcopy(raw)


class BoolOption(Option[bool]):
    def normalize(self, raw: Any) -> bool:
        if not isinstance(raw, bool):
            raise ValueError(f"{self.name!r} expects a bool, got {raw!r}")
        return raw


class RangeOption(Option[T]):
    """A number clamped to ``[minimum, maximum]``. The type (int / float) follows the default value."""

    def __init__(self, default: T, minimum: T, maximum: T) -> None:
        super().__init__(default)
        self.minimum = minimum
        self.maximum = maximum

    def normalize(self, raw: Any) -> T:
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise ValueError(f"{self.name!r} expects a number, got {raw!r}")
        try:
            if not math.isfinite(raw):
                raise ValueError(f"{self.name!r} expects a finite number")
            value = round(raw) if isinstance(self.default, int) else float(raw)
        except OverflowError as e:
            raise ValueError(f"{self.name!r} number is out of range") from e
        return min(max(value, self.minimum), self.maximum)  # type: ignore[return-value]


class ChoiceOption(Option[T]):
    def __init__(self, default: T, choices: Sequence[T]) -> None:
        super().__init__(default)
        self.choices = tuple(choices)
        if default not in self.choices:
            raise ValueError(f"default {default!r} is not one of {self.choices!r}")

    def normalize(self, raw: Any) -> T:
        if raw not in self.choices:
            raise ValueError(f"{self.name!r} expects one of {self.choices!r}, got {raw!r}")
        return raw


_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class ColorOption(Option[str]):
    """Color stored as ``#RRGGBB`` or ``#AARRGGBB``."""

    def normalize(self, raw: Any) -> str:
        if not isinstance(raw, str) or not _COLOR_RE.match(raw):
            raise ValueError(f"{self.name!r} expects a hex color, got {raw!r}")
        return raw.lower()


# ---------------------------------------------------------------------------
# Items and groups: live, observable values bound to a store
# ---------------------------------------------------------------------------


class ConfigItem(QObject, Generic[T]):
    """A live config value. Emits ``valueChanged(new_value)`` after every effective change."""

    valueChanged = pyqtSignal(object)

    def __init__(self, option: Option[T], value: T, on_change: Callable[[str, Any], None]) -> None:
        super().__init__()
        self.option = option
        self._value = value
        self._on_change = on_change

    @property
    def key(self) -> str:
        return self.option.name

    @property
    def value(self) -> T:
        return self._value

    @property
    def default(self) -> T:
        return self.option.default

    def set(self, value: T) -> None:
        """Validate and apply ``value``. Raises :class:`ValueError` for invalid input."""
        value = self.option.normalize(value)
        if value == self._value:
            return
        self._value = value
        self._on_change(self.key, value)
        self.valueChanged.emit(value)

    def reset(self) -> None:
        self.set(copy.deepcopy(self.option.default))

    def __repr__(self) -> str:
        return f"ConfigItem({self.key}={self._value!r})"


class ConfigGroup:
    """Base class for a set of options stored under one namespace (e.g. ``plugins.day_timer``)."""

    def __init__(self, namespace: str, stored: dict[str, Any], on_change: Callable[[str, Any], None]) -> None:
        self.namespace = namespace
        self._items: dict[str, ConfigItem[Any]] = {}
        for name, option in self.options().items():
            value = copy.deepcopy(option.default)
            if name in stored:
                try:
                    value = option.normalize(stored[name])
                except ValueError as e:
                    log.warning("Config %s.%s reset to default: %s", namespace, name, e)
            self._items[name] = ConfigItem(option, value, on_change)

    @classmethod
    def options(cls) -> dict[str, Option[Any]]:
        """All options declared on this class and its bases, in declaration order."""
        result: dict[str, Option[Any]] = {}
        for klass in reversed(cls.__mro__):
            for name, attr in vars(klass).items():
                if isinstance(attr, Option):
                    result[name] = attr
        return result

    def item(self, name: str) -> ConfigItem[Any]:
        return self._items[name]

    def items(self) -> dict[str, ConfigItem[Any]]:
        return dict(self._items)

    def reset_all(self) -> None:
        for item in self._items.values():
            item.reset()


# ---------------------------------------------------------------------------
# Store: owns the YAML document and persists changes
# ---------------------------------------------------------------------------


class ConfigStore(QObject):
    """Holds the settings document and writes it back with debouncing and atomic replacement."""

    SAVE_DELAY_MS = 500
    saveFailed = pyqtSignal(str)

    def __init__(self, path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self._data: dict[str, Any] = {}
        self._groups: list[ConfigGroup] = []
        self._import_pending = False
        self._dirty = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self.SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.flush)
        self._load()

    def bind(self, group_cls: type[G], namespace: str) -> G:
        section = self._section(namespace, create=False) or {}

        def on_change(key: str, value: Any) -> None:
            # Import is followed immediately by restart. Shutdown callbacks may still write old state.
            if self._import_pending:
                return
            self._section(namespace, create=True)[key] = copy.deepcopy(value)
            self._mark_dirty()

        group = group_cls(namespace, section, on_change)
        self._groups.append(group)
        return group

    def export_file(self, path: Path) -> None:
        """Export all namespaces, including unchanged defaults and unknown plugin settings."""
        data = copy.deepcopy(self._data)
        for group in self._groups:
            section = data
            for part in group.namespace.split("."):
                if not isinstance(section.get(part), dict):
                    section[part] = {}
                section = section[part]
            for key, item in group.items().items():
                # The persisted document holds the latest write if a namespace was bound twice.
                try:
                    section[key] = item.option.normalize(section.get(key, item.value))
                except (ValueError, TypeError, OverflowError):
                    section[key] = copy.deepcopy(item.default)
        self._write_document(path, data)

    def read_import_file(self, path: Path) -> dict[str, Any]:
        """Read and validate a complete replacement without modifying current settings."""
        with path.open(encoding="utf-8-sig") as source:
            data = yaml.safe_load(source)
        self._validate_import(data)
        return data

    def replace_for_restart(self, data: dict[str, Any]) -> None:
        """Atomically replace all settings, then protect them from writes during immediate restart.

        Existing ConfigItems deliberately stay unchanged; callers must restart after success.
        A failed write leaves both the running configuration and the original file intact.
        """
        self._validate_import(data)
        replacement = copy.deepcopy(data)
        self._write_document(self.path, replacement)
        self._save_timer.stop()
        self._data = replacement
        self._dirty = False
        self._import_pending = True

    def _validate_import(self, data: Any) -> None:
        if not isinstance(data, dict) or not data:
            raise ValueError("Settings must be a non-empty YAML mapping")

        def validate(value: Any, ancestors: frozenset[int] = frozenset()) -> None:
            if isinstance(value, dict | list):
                if id(value) in ancestors:
                    raise ValueError("Recursive YAML aliases are not supported")
                ancestors = ancestors | {id(value)}
                if isinstance(value, dict):
                    if any(not isinstance(key, str) for key in value):
                        raise ValueError("Settings keys must be strings")
                    values = value.values()
                else:
                    values = value
                for child in values:
                    validate(child, ancestors)
            elif not isinstance(value, str | int | float | bool | type(None)):
                raise ValueError("Unsupported setting value")
            elif isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Settings numbers must be finite")

        validate(data)
        roots = {group.namespace.split(".")[0] for group in self._groups}
        if not roots.intersection(data):
            raise ValueError("No application settings found")
        for group in self._groups:
            section = data
            for part in group.namespace.split("."):
                section = section.get(part, {})
                if not isinstance(section, dict):
                    raise ValueError(f"Expected a settings mapping: {group.namespace}")
            for key, item in group.items().items():
                if key in section:
                    item.option.normalize(section[key])

    @staticmethod
    def _write_document(path: Path, data: dict[str, Any]) -> None:
        """Write beside the destination and replace it only after serialization succeeds."""
        temporary: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as target:
                temporary = Path(target.name)
                yaml.safe_dump(data, target, allow_unicode=True, sort_keys=False)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    log.warning("Could not remove temporary settings file %s", temporary, exc_info=True)

    def flush(self) -> None:
        """Write pending changes to disk immediately."""
        self._save_timer.stop()
        if not self._dirty:
            return
        try:
            self._write_document(self.path, self._data)
            self._dirty = False
        except (OSError, yaml.YAMLError) as e:
            log.exception("Failed to save settings to %s", self.path)
            self.saveFailed.emit(str(e))

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise ValueError("top level must be a mapping")
            self._data = data
        except (OSError, yaml.YAMLError, ValueError) as e:
            backup = self.path.with_name(f"{self.path.stem}.broken-{int(time.time())}{self.path.suffix}")
            try:
                os.replace(self.path, backup)
            except OSError:
                log.exception("Settings could not be read (%s); backup failed; original preserved", e)
            else:
                log.error("Settings file could not be read (%s); moved to %s", e, backup)
            self._data = {}

    def _section(self, namespace: str, *, create: bool) -> dict[str, Any] | None:
        node = self._data
        for part in namespace.split("."):
            child = node.get(part)
            if not isinstance(child, dict):
                if not create:
                    return None
                child = node[part] = {}
            node = child
        return node

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._save_timer.start()
