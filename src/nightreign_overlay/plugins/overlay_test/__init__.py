"""Overlay test plugin: a small painted overlay exercising the overlay infrastructure.

It covers dragging, scaling, opacity, click-through, focus based visibility, the window-mode fallback, event
bus subscriptions and service registration — without depending on the game.
"""

from nightreign_overlay.plugins.overlay_test.plugin import OverlayTestPlugin

PLUGIN = OverlayTestPlugin

__all__ = ["PLUGIN"]
