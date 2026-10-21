"""Legacy latency colours and independent overlay defaults."""

from nightreign_overlay.core.config import BoolOption, ConfigGroup, RangeOption
from nightreign_overlay.ui.overlay import OverlayConfig


class P2PConfig(ConfigGroup):
    show_playtime = BoolOption(True)
    good_ping = RangeOption(80, 1, 999)
    warning_ping = RangeOption(150, 2, 2000)

    def enforce_thresholds(self, _value: object = None) -> None:
        self.warning_ping.set(max(self.good_ping.value + 1, self.warning_ping.value))


class P2POverlayConfig(OverlayConfig):
    opacity = RangeOption(75, 10, 100)
