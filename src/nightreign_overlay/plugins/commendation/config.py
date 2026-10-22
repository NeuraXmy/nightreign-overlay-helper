from nightreign_overlay.core.config import ConfigGroup, Option, RangeOption
from nightreign_overlay.ui.overlay import OverlayConfig


class CommendationConfig(ConfigGroup):
    close_seconds = RangeOption(120, 10, 600)
    comment = Option(
        "+rep 好队友，感谢一起征战黑夜君临！",
        validator=lambda value: (
            isinstance(value, str) and 1 <= len(value.strip()) <= 500 and "\0" not in value
        ),
    )


class CommendationOverlayConfig(OverlayConfig):
    opacity = RangeOption(90, 10, 100)
