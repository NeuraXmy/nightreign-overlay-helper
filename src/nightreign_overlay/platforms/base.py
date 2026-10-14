"""Interface implemented by every platform backend."""

from __future__ import annotations


class PlatformBackend:
    """Default implementation: every optional capability is unsupported."""

    #: Short identifier shown in the UI and logs ("windows", "macos", ...).
    name: str = "unknown"
    #: Whether :meth:`foreground_window_title` returns meaningful data.
    supports_foreground_detection: bool = False
    #: Whether frameless, translucent, always-on-top overlays are expected to render correctly.
    supports_transparent_overlay: bool = False

    def foreground_window_title(self) -> str | None:
        """Title of the window that currently has keyboard focus, or None if unknown."""
        return None

    def ensure_topmost(self, window_id: int) -> None:
        """Re-assert always-on-top for a native window (games in borderless mode may cover overlays)."""

    def configure_overlay_activation(self, window_id: int, non_activating: bool) -> None:
        """Allow mouse interaction without activating the application for transparent overlays."""

    def is_admin(self) -> bool:
        return False

    def has_screen_capture_access(self) -> bool:
        """Whether screenshots contain other applications' windows (macOS gates this behind a permission)."""
        return True

    def request_screen_capture_access(self) -> None:
        """Ask the operating system for screen capture permission where it is gated."""
