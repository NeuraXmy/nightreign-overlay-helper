"""Minimal platform backend shared by overlay and feature tests."""

from nightreign_overlay.platforms import PlatformBackend


class FakeBackend(PlatformBackend):
    name = "fake"
    supports_foreground_detection = True
    supports_transparent_overlay = True

    def __init__(self) -> None:
        self.title: str | None = None

    def foreground_window_title(self) -> str | None:
        return self.title
