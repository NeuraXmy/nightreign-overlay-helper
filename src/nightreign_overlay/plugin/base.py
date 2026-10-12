"""Plugin protocol: manifest + lifecycle hooks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

from PyQt6.QtCore import QObject

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget

    from nightreign_overlay.plugin.context import PluginContext


class PluginKind(StrEnum):
    #: Provides capabilities to other plugins (capture, hotkeys, shared HUD...).
    INFRASTRUCTURE = "infrastructure"
    #: A user facing feature.
    FEATURE = "feature"
    #: Development / diagnostics tools.
    DEBUG = "debug"


class SettingsScope(StrEnum):
    """Where, if anywhere, a plugin exposes its settings in the user interface."""

    #: The plugin has its own navigation page.
    PAGE = "page"
    #: The plugin contributes its settings to the general settings page.
    GENERAL = "general"
    #: The plugin has no direct settings entry; features expose its actions where relevant.
    HIDDEN = "hidden"


#: User-facing plugin group order. Lifecycle order remains dependency-driven in ``PluginManager``.
PLUGIN_KIND_DISPLAY_ORDER = (PluginKind.FEATURE, PluginKind.INFRASTRUCTURE, PluginKind.DEBUG)


@dataclass(frozen=True)
class PluginManifest:
    """Static description of a plugin.

    The display name and description are not part of the manifest; they are read from the plugin's own
    translations (keys ``plugin.name`` and ``plugin.description``).
    """

    id: str
    version: str = "1.0.0"
    kind: PluginKind = PluginKind.FEATURE
    #: Name of a ``qfluentwidgets.FluentIcon`` member used in navigation.
    icon: str = "APPLICATION"
    #: Plugins that must be active before this one can be activated.
    requires: tuple[str, ...] = ()
    #: Plugins that are used when present; they only influence the activation order.
    optional: tuple[str, ...] = ()
    #: Explicit initial state override. ``None`` follows the default for :attr:`kind`.
    default_enabled: bool | None = None
    #: Controls the settings entry independently of the plugin's runtime role.
    settings_scope: SettingsScope = SettingsScope.PAGE
    #: Sort key inside its kind group (navigation, home page).
    order: int = 100

    @property
    def initial_enabled(self) -> bool:
        """Initial state when the user has not persisted an explicit choice."""
        return self.kind != PluginKind.DEBUG if self.default_enabled is None else self.default_enabled


class Plugin(QObject):
    """Base class for plugins.

    Lifecycle:

    * ``on_load`` — called once after construction, whether or not the plugin is enabled. Bind configuration
      here so settings pages work for disabled plugins too.
    * ``on_activate`` / ``on_deactivate`` — may be called repeatedly as the user toggles the plugin. Resources
      registered through :class:`PluginContext` (services, subscriptions, cleanups) are released automatically
      after ``on_deactivate``.
    """

    manifest: ClassVar[PluginManifest]

    def __init__(self, ctx: PluginContext) -> None:
        super().__init__()
        self.ctx = ctx

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def name(self) -> str:
        return self.ctx.tr("plugin.name")

    @property
    def description(self) -> str:
        return self.ctx.tr("plugin.description")

    def on_load(self) -> None:
        """Bind configuration and prepare lightweight state."""

    def on_activate(self) -> None:
        """Start working: create overlays, register services, subscribe to events."""

    def on_deactivate(self) -> None:
        """Stop working and release resources not managed by the context."""

    def create_settings_widget(self, parent: QWidget) -> QWidget | None:
        """Return the content of the "Settings" tab, or None if the plugin has no settings."""
        return None
