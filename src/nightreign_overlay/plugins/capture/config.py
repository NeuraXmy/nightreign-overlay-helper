from __future__ import annotations

from nightreign_overlay.core.config import BoolOption, ChoiceOption, ConfigGroup, RangeOption, StringOption

#: Mode keys map to MaaWin32Screencap method bitmasks (see win32.SCREENCAP_METHOD_MASKS).
#: A single concrete method (gdi … screendc) pins the capture method; auto speed-tests all of them.
CAPTURE_MODES = (
    "auto",
    "foreground",
    "background",
    "gdi",
    "framepool",
    "dxgi_desktop_dup",
    "dxgi_desktop_dup_window",
    "printwindow",
    "screendc",
)


class CaptureConfig(ConfigGroup):
    mode = ChoiceOption("auto", CAPTURE_MODES)
    #: Process image name owning the capture window (e.g. a PS5 remote-play app); empty = auto-detect
    #: the game window by title.
    process = StringOption("")
    interval_ms = RangeOption(250, 50, 2000)
    hdr_processing = BoolOption(False)
