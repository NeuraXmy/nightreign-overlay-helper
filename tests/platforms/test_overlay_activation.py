"""Native macOS overlay activation behavior, without requiring a visible desktop."""

import sys
from types import SimpleNamespace

from nightreign_overlay.platforms.generic import GenericBackend


def test_macos_panel_nonactivation_preserves_other_styles(monkeypatch):
    style = [0x20]
    window = SimpleNamespace(
        styleMask=lambda: style[0], setStyleMask_=lambda value: style.__setitem__(0, value)
    )
    view = SimpleNamespace(window=lambda: window)
    monkeypatch.setitem(sys.modules, "Cocoa", SimpleNamespace(NSWindowStyleMaskNonactivatingPanel=0x80))
    monkeypatch.setitem(sys.modules, "objc", SimpleNamespace(objc_object=lambda **kwargs: view))
    monkeypatch.setattr(sys, "platform", "darwin")
    backend = GenericBackend("macos")
    backend.configure_overlay_activation(123, True)
    assert style[0] == 0xA0
    backend.configure_overlay_activation(123, False)
    assert style[0] == 0x20
