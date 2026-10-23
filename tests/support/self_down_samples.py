"""Real self-down labels, legacy checks and continuous fill preserving separators.

These are synthetic progress frames, not a recording of the game's animation.
"""

from pathlib import Path

import cv2
import numpy as np

from nightreign_overlay.core.images import read_cv2_image

from .hud_images import variants as variants

SAMPLES = Path(__file__).parents[1] / "data/entertainment"


def labeled_samples(root=SAMPLES):
    """Real labeled icons and the same bounded backgrounds as the legacy test."""
    for path in sorted((root / "self_down").glob("down*.png")):
        rgb = cv2.cvtColor(read_cv2_image(path), cv2.COLOR_BGR2RGB)
        yield path.name, True, rgb
        h, w = rgb.shape[:2]
        background = "game.png" if path.stem == "down" else "game2.png"
        game = cv2.cvtColor(read_cv2_image(root / "self_down" / background), cv2.COLOR_BGR2RGB)
        width, height = game.shape[1] - w + 1, game.shape[0] - h + 1
        for number, position in enumerate(
            np.random.default_rng(20261023).choice(width * height, 10, replace=False)
        ):
            y, x = divmod(int(position), width)
            yield f"{path.stem}-background-{number:02d}", False, game[y : y + h, x : x + w]
    for path in sorted((root / "self_down_video").glob("*.jpg")):
        label = path.stem.rsplit("_", 1)[1]
        if label not in ("0", "1", "2", "3"):
            raise ValueError(f"Unknown self-down label: {path.name}")
        yield path.name, label != "0", cv2.cvtColor(read_cv2_image(path), cv2.COLOR_BGR2RGB)


def legacy_variants(rgb):
    """The original 43 positive-icon checks, including calibration offsets."""
    h, w = rgb.shape[:2]
    yield "original", rgb
    yield "blur", cv2.GaussianBlur(rgb, (7, 7), 2)
    for saturation in (0.5, 1, 1.5):
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = np.clip(hsv[..., 1].astype(float) * saturation, 0, 255)
        colored = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(float)
        for contrast in (0.6, 1, 1.4):
            for brightness in (0.6, 1, 1.4):
                yield (
                    (saturation, contrast, brightness),
                    np.clip(((colored - 127.5) * contrast + 127.5) * brightness, 0, 255).astype(np.uint8),
                )
    yield "sharpen", cv2.addWeighted(rgb, 1.8, cv2.GaussianBlur(rgb, (5, 5), 1), -0.8, 0)
    for size in (48, 80, 160, 230):
        yield ("size", size), cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
    for dx in (-5, 0, 5):
        for dy in (-5, 0, 5):
            yield (
                ("offset", dx, dy),
                cv2.warpAffine(
                    rgb, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h), borderMode=cv2.BORDER_REFLECT
                ),
            )


def continuous_variants(rgb):
    """All 5,089 checks of synthetic fill progress used by tests and timing."""
    for degrees, image in continuous_progress(rgb):
        hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = (hsv[..., 1].astype(float) * 0.5).astype(np.uint8)
        low_sat = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
        images = {
            "original": image,
            "dim": np.clip(image.astype(float) * 0.6, 0, 255).astype(np.uint8),
            "bright": np.clip(image.astype(float) * 1.4, 0, 255).astype(np.uint8),
            "low_saturation": low_sat,
            "clipped": np.clip(((low_sat.astype(float) - 127.5) * 1.4 + 127.5) * 1.4, 0, 255).astype(
                np.uint8
            ),
            "blur": cv2.GaussianBlur(image, (7, 7), 2),
            "offset": cv2.warpAffine(
                image,
                np.float32([[1, 0, 5], [0, 1, -5]]),
                (image.shape[1], image.shape[0]),
                borderMode=cv2.BORDER_REFLECT,
            ),
        }
        for name, variant in images.items():
            yield (float(degrees), name), variant


def continuous_progress(rgb: np.ndarray):
    h, w = rgb.shape[:2]
    y, x = np.mgrid[:h, :w]
    nx, ny = (x - (w - 1) / 2) / (w / 2), (y - (h - 1) / 2) / (h / 2)
    radius = np.hypot(nx, ny)
    angle = (np.degrees(np.arctan2(ny, nx)) + 90) % 360
    separator = np.minimum.reduce([np.abs((angle - center + 180) % 360 - 180) for center in (0, 120, 240)])
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    # Only repaint bright purple pixels; preserve black outlines, separator
    # spokes, central disk and all scene pixels outside the annulus.
    mask = (
        (radius > 0.34)
        & (radius < 0.90)
        & (separator > 7)
        & (hsv[..., 0] > 110)
        & (hsv[..., 0] < 155)
        & (hsv[..., 1] > 65)
        & (hsv[..., 2] > 100)
    )
    empty = rgb.copy()
    empty[mask] = (40, 40, 40)
    angles = sorted(set(np.linspace(0, 360, 721)) | {0.01, 119.9, 120.1, 239.9, 240.1, 359.99})
    for degrees in angles:
        image = empty.copy()
        filled = mask & (angle < degrees)
        image[filled] = rgb[filled]
        yield degrees, image
