"""Default HUD rectangles in physical pixels, calibrated against a 2560 x 1440 client area."""

from PyQt6.QtCore import QRect

_REFERENCE_SIZE = (2560, 1440)
_REFERENCE_REGIONS = {
    "day_timer.detect_region": (1112, 733, 342, 95),
    "rain_timer.hp_region": (240, 58, 20, 8),
    "map_detect.map_region": (1454, 228, 990, 990),
    "hp_marker.hpbar_region": (224, 56, 134, 15),
    "art_timer.art_region": (1206, 1260, 143, 140),
    "entertainment.teammates": (65, 216, 457, 249),
}
_MANUAL_ONLY_REGIONS = {"capture.game_window"}


def supports_automatic_region(key: str) -> bool:
    return key in _REFERENCE_REGIONS or key in _MANUAL_ONLY_REGIONS


def automatic_region(key: str, client: QRect | None) -> QRect | None:
    """Scale the default HUD within the actual game client, never the virtual desktop.

    Non-16:9 clients and small/transient windows require manual calibration. A small ratio tolerance
    permits integer rounding for windowed clients. No calculated rectangle is written to settings.
    """
    reference = _REFERENCE_REGIONS.get(key)
    if key in _MANUAL_ONLY_REGIONS:
        return QRect(client) if client is not None and not client.isEmpty() else None
    if reference is None or client is None or client.width() < 640 or client.height() < 360:
        return None
    if abs(client.width() / client.height() - 16 / 9) > 0.01:
        return None
    sx, sy = client.width() / _REFERENCE_SIZE[0], client.height() / _REFERENCE_SIZE[1]
    x, y, width, height = reference
    width, height = max(1, round(width * sx)), max(1, round(height * sy))
    if key == "map_detect.map_region":
        width = height = min(width, height)
    return QRect(client.x() + round(x * sx), client.y() + round(y * sy), width, height)
