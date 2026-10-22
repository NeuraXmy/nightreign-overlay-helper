from nightreign_overlay.plugins.audio.loop_stack import LoopAudioEntry, LoopAudioStack


def test_loop_stack_removes_arbitrary_entry_and_restores_previous_top() -> None:
    stack = LoopAudioStack()
    lower = LoopAudioEntry("lower", "lower.wav", 50, 0.2)
    middle = LoopAudioEntry("middle", "middle.wav", 60, 0.1)
    top = LoopAudioEntry("top", "top.wav", 70, 0)

    stack.put(lower)
    stack.put(middle)
    stack.put(top)
    assert stack.top is top
    assert stack.remove("middle") is middle
    assert stack.top is top
    assert stack.remove("top") is top
    assert stack.top is lower


def test_put_moves_existing_owner_to_top_and_updates_fade_out() -> None:
    stack = LoopAudioStack()
    stack.put(LoopAudioEntry("one", "one.wav", 100, 0))
    stack.put(LoopAudioEntry("two", "two.wav", 100, 0))
    replacement = LoopAudioEntry("one", "new.wav", 80, 0.5)

    stack.put(replacement)
    stack.set_fade_out("one", 1.25)

    assert stack.top is replacement
    assert replacement.fade_out == 1.25
    assert stack.remove("two") is not None
    assert stack.top is replacement


def test_arbitrary_removal_keeps_lower_entry_available() -> None:
    stack = LoopAudioStack()
    stack.put(LoopAudioEntry("bottom", "a.wav", 10, 0))
    stack.put(LoopAudioEntry("middle", "b.wav", 20, 0))
    stack.put(LoopAudioEntry("top", "c.wav", 30, 0))

    stack.remove("middle")
    stack.remove("top")

    assert stack.top is not None
    assert stack.top.owner == "bottom"


def test_loop_and_finite_owners_are_separate_by_contract() -> None:
    """Stack entries represent only loops; finite playback uses another owner slot."""
    stack = LoopAudioStack()
    stack.put(LoopAudioEntry("loop", "loop.wav", 100, 0))
    finite_owner = "notification"

    assert stack.top is not None
    assert stack.top.owner == "loop"
    assert stack.get(finite_owner) is None
