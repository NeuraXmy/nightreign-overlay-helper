"""Pure down-state playback transition rules."""

from nightreign_overlay.plugins.entertainment.detector import Teammate


def should_start(teammates: tuple[Teammate, Teammate], condition: str) -> bool:
    present = [teammate for teammate in teammates if teammate.present]
    if not present:
        return False
    if condition == "all_three":
        return all(teammate.down and teammate.stages == 3 for teammate in present)
    return all(teammate.down for teammate in present)


def should_stop(teammates: tuple[Teammate, Teammate], condition: str) -> bool:
    present = [teammate for teammate in teammates if teammate.present]
    if not present:
        return True
    if condition == "any_up":
        return any(not teammate.down for teammate in present)
    return all(not teammate.down for teammate in present)
