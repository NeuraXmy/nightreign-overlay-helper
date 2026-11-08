from __future__ import annotations

from nightreign_overlay.core.config import BoolOption, ChoiceOption, ConfigGroup, RangeOption, StringOption

#: Mode keys map to MaaWin32Screencap method bitmasks (see win32.SCREENCAP_METHOD_MASKS).
#: User-facing modes always pin a concrete method. Detection is an explicit one-shot operation.
CAPTURE_MODES = (
    "gdi",
    "framepool",
    "dxgi_desktop_dup",
    "dxgi_desktop_dup_window",
    "printwindow",
    "screendc",
    "mss",
)


class _CaptureModeOption(ChoiceOption[str]):
    def normalize(self, raw: object) -> str:
        # Legacy speed-test modes migrate to the safe default, without running a benchmark at capture time.
        if isinstance(raw, str) and raw in {"auto", "foreground", "background"}:
            return "mss"
        return super().normalize(raw)


class CaptureConfig(ConfigGroup):
    mode = _CaptureModeOption("mss", CAPTURE_MODES)
    detection_prompted = BoolOption(False)
    #: Process image name owning the capture window (e.g. a PS5 remote-play app); empty = auto-detect
    #: the game window by title.
    process = StringOption("")
    interval_ms = RangeOption(250, 50, 2000)
    hdr_processing = BoolOption(False)
