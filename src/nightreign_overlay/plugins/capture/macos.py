"""macOS window enumeration for the manual capture-process picker."""

from __future__ import annotations

import os


def list_window_processes() -> list[tuple[str, str]]:
    """List visible on-screen windows as ``(title, executable name)`` pairs."""
    from AppKit import NSRunningApplication
    from Quartz import (  # type: ignore[import-not-found]
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowListOptionOnScreenOnly,
        kCGWindowListExcludeDesktopElements,
        kCGWindowLayer,
        kCGWindowOwnerPID,
        kCGWindowName,
    )

    current_pid = os.getpid()
    windows: dict[int, tuple[str, str]] = {}
    for window in CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
        kCGNullWindowID,
    ) or ():
        pid = int(window.get(kCGWindowOwnerPID, 0))
        if not pid or pid == current_pid or pid in windows or int(window.get(kCGWindowLayer, 0)) != 0:
            continue
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            continue
        executable = app.executableURL()
        image = executable.lastPathComponent() if executable else app.localizedName()
        if not image:
            continue
        title = str(window.get(kCGWindowName, "") or app.localizedName() or image)
        windows[pid] = (title, str(image))
    return sorted(windows.values(), key=lambda entry: (entry[1].casefold(), entry[0].casefold()))
