from nightreign_overlay.plugins.entertainment.detector import Teammate
from nightreign_overlay.plugins.entertainment.state import should_start, should_stop


def _mate(*, present: bool = True, down: bool = False, stages: int = 0) -> Teammate:
    return Teammate(present, down, stages, 1.0, (0.0, 0.0))


def test_start_rules_use_existing_teammates_only() -> None:
    all_down = (_mate(down=True, stages=1), _mate(down=True, stages=3))
    all_three = (_mate(down=True, stages=3), _mate(down=True, stages=3))
    assert should_start(all_down, "all_down")
    assert not should_start(all_down, "all_three")
    assert should_start(all_three, "all_three")
    assert should_start((_mate(down=True), _mate(present=False)), "all_down")
    assert not should_start((_mate(present=False), _mate(present=False)), "all_down")


def test_stop_rules_and_no_teammate_override() -> None:
    all_up = (_mate(), _mate())
    partly_up = (_mate(), _mate(down=True, stages=3))
    all_down = (_mate(down=True), _mate(down=True, stages=3))
    absent = (_mate(), _mate(present=False))
    no_teammates = (_mate(present=False), _mate(present=False))
    assert should_stop(all_up, "all_up")
    assert not should_stop(partly_up, "all_up")
    assert should_stop(partly_up, "any_up")
    assert not should_stop(all_down, "any_up")
    assert should_stop(absent, "all_up")
    assert should_stop(absent, "any_up")
    assert should_stop(no_teammates, "all_up")
