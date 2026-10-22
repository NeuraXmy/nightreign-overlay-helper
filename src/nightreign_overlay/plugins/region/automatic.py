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


def _centered_16_9_client(client: QRect) -> QRect:
    """Return the largest 16:9 rectangle centered inside the game client."""
    client_width, client_height = client.width(), client.height()
    if client_width * 9 >= client_height * 16:
        # Ultrawide: remove the side margins.
        width = client_height * 16 // 9
        height = client_height
    else:
        # Taller/narrower client: remove the top and bottom margins.
        width = client_width
        height = client_width * 9 // 16
    return QRect(
        client.x() + (client_width - width) // 2,
        client.y() + (client_height - height) // 2,
        width,
        height,
    )


def automatic_region(key: str, client: QRect | None) -> QRect | None:
    """Scale the default HUD within a centered 16:9 area of the game client.

    Non-16:9 clients are cropped around their center before the 16:9 reference layout is
    scaled. No calculated rectangle is written to settings.
    """
    reference = _REFERENCE_REGIONS.get(key)
    if key in _MANUAL_ONLY_REGIONS:
        return QRect(client) if client is not None and not client.isEmpty() else None
    if reference is None or client is None or client.isEmpty():
        return None
    if abs(client.width() / client.height() - 16 / 9) > 0.01:
        client = _centered_16_9_client(client)
    if client.width() < 640 or client.height() < 360:
        return None
    sx, sy = client.width() / _REFERENCE_SIZE[0], client.height() / _REFERENCE_SIZE[1]
    x, y, width, height = reference
    width, height = max(1, round(width * sx)), max(1, round(height * sy))
    if key == "map_detect.map_region":
        width = height = min(width, height)
    return QRect(client.x() + round(x * sx), client.y() + round(y * sy), width, height)
