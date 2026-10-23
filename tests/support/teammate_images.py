"""Filename ground truth and deterministic teammate HUD enhancements."""

from pathlib import Path

from .hud_images import variants as variants

SAMPLES = Path(__file__).parents[1] / "data/entertainment"


def sample_paths(root=SAMPLES):
    return sorted(root.glob("go_down*/*.png")) + sorted(root.glob("teammate_video/*.jpg"))


def expected_states(path):
    stem = path.stem.split("(")[0]
    labels = stem.split("_")[-1].split("-") if "-" in stem else stem.split("_")
    return tuple("1" if label == "2" else label for label in labels)


def states(teammates):
    return tuple(
        "n" if not t.present else "0" if not t.down else "3" if t.stages == 3 else "1" for t in teammates
    )
