"""Generate synthetic 64x64 POI crops for the small-map detector.

Each sample is made from a random crop of one of ``assets/bg`` maps with a
POI centered on the crop.  The icon dimensions follow the constants used by
``test.ipynb``.  Labels are written as JSONL so additional fields can be
added without changing the image layout.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

MAP_SIZE = (750, 750)
OUTPUT_SIZE = (64, 64)
POI_SIZE = (45, 45)
POI_ICON_SCALE = {
    30: 0.35,
    32: 0.5,
    34: 0.4,
    37: 0.4,
    38: 0.3,
    40: 0.5,
    41: 0.38,
    510: 0.38,
    511: 0.4,
    500: 0.15,
    501: 0.2,
    524: 0.3,
    525: 0.4,
    535: 0.15,
    536: 0.18,
}
NO_BASE_RATE = 0.4
NO_CORNER_RATE = 0.3
POI_ICON_OFFSET = {500: (0, -3), 501: (0, 3), 535: (-3, -3), 536: (0, -2)}
CORNER_SIZE = (int(MAP_SIZE[0] * 0.0195), int(MAP_SIZE[1] * 0.0195))
VARIANT_PROBABILITIES = (0.7, 0.1, 0.2)  # none, var/00, var/01
SIZE_SCALE_MIN = 0.8
SIZE_SCALE_MAX = 1.2
POSITION_OFFSET_MAX = 5
CENTER_SIGMA = OUTPUT_SIZE[0] / 10
SIZE_SIGMA = 0.033
BLUE_OVERLAY_PROBABILITY = 0.2
# Approximate the dark blue outside the outer ring in the reference map.jpg.
BLUE_OVERLAY_COLOR = (28, 47, 66)
BLUE_OVERLAY_COLOR_SIGMA = 5.0
BLUE_OVERLAY_ALPHA = 88
BLUE_OVERLAY_ALPHA_SIGMA = 10.0
BRIGHTNESS_RANGE = (0.5, 2.0)
BRIGHTNESS_MEAN = 1.0
BRIGHTNESS_SIGMA = 0.1
# Contrast / saturation are biased below 1.0 so a fair share of samples look
# washed-out (gray); the upper tail still yields a few over-saturated cases.
# factor semantics: 1.0 = unchanged, 0.0 = fully gray, >1 = stronger.
CONTRAST_RANGE = (0.1, 2.0)
CONTRAST_MEAN = 1.0
CONTRAST_SIGMA = 0.4
SATURATION_RANGE = (0.1, 2.0)
SATURATION_MEAN = 0.85
SATURATION_SIGMA = 0.4
SHARPEN_PROBABILITY = 0.6
SHARPEN_RANGE = (1.15, 5.0)
BLUR_RADIUS_RANGE = (0.35, 0.5)
STRETCH_RANGE = (1.0, 1.1)
STRETCH_SIGMA = 0.03
GAME_BLEND_PROBABILITY = 0.1
GAME_ALPHA_RANGE = (0.5, 0.75)
OTHER_COUNT_PROBABILITIES = (0.4, 0.4, 0.2)
OTHER_SELECTION_PROBABILITIES = {0: 0.3, 1: 0.4, 2: 0.05, 3: 0.05, 4: 0.05, 5: 0.05, 6: 0.00, 7: 0.05}
OTHER_BASE_SCALE = {0: 0.15, 1: 0.15, 2: 0.15, 3: 0.15, 4: 0.15, 5: 0.15, 6: 0.5, 7: 0.2}
OTHER_BEFORE_BASE = {0: False, 1: True, 2: True, 3: True, 4: True, 5: False, 6: False, 7: False}
PLAYER_PROBABILITY = 0.1
PLAYER_BASE_SCALE = 0.8  # player longest side as a fraction of OUTPUT_SIZE
PLAYER_COLORS = ("blue", "green", "red")
PLAYER_COLOR_HUES = {"green": 120.0, "red": 0.0}  # "blue" keeps the source icon
PLAYER_SATURATION_THRESHOLD = 0.15
PLAYER_BRIGHTNESS = 1.15  # slightly brighter
PLAYER_SATURATION = 0.85  # slightly less saturated
PLAYER_CENTER_CLEARANCE = 0.25  # min marker-centre distance from crop centre (x OUTPUT_SIZE)
PLAYER_POSITION_TRIES = 8
RESOLUTION_DEGRADE_PROBABILITY = 0.8
RESOLUTION_DEGRADE_LEVELS = (0.2, 0.3, 0.4)
RESOLUTION_DEGRADE_RESAMPLING = (Image.Resampling.BILINEAR, Image.Resampling.BICUBIC)


def _numbered_files(directory: Path, suffixes: Iterable[str]) -> dict[int, Path]:
    result = {}
    for path in directory.iterdir():
        if path.suffix.lower() not in suffixes:
            continue
        try:
            result[int(path.stem)] = path
        except ValueError:
            continue
    return result


def _read_meta(path: Path) -> dict[int, int]:
    """Read ``base/meta.txt`` entries such as ``00.png:30``."""
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or ":" not in line:
            continue
        filename, value = line.split(":", 1)
        try:
            result[int(Path(filename.strip()).stem)] = int(value.strip())
        except ValueError:
            raise ValueError(f"Invalid metadata line: {line!r}") from None
    return result


def _resize_icon(image: Image.Image, scale: float) -> Image.Image:
    size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
    return image.resize(size, Image.Resampling.BICUBIC)


_DEGRADED_VARIANT_CACHE: dict[int, tuple[Image.Image, dict[tuple[float, int], Image.Image]]] = {}


def _degraded_variants(image: Image.Image) -> dict[tuple[float, int], Image.Image]:
    """Precompute the resolution-loss versions once per source image.

    Each entry downscales to one of ``RESOLUTION_DEGRADE_LEVELS`` and scales
    back to the original size, so sampling only needs a dictionary lookup.
    """
    cached = _DEGRADED_VARIANT_CACHE.get(id(image))
    if cached is not None and cached[0] is image:
        return cached[1]
    variants: dict[tuple[float, int], Image.Image] = {}
    for level in RESOLUTION_DEGRADE_LEVELS:
        small = (max(1, round(image.width * level)), max(1, round(image.height * level)))
        for resample in RESOLUTION_DEGRADE_RESAMPLING:
            variants[(level, resample)] = image.resize(small, resample).resize(image.size, resample)
    _DEGRADED_VARIANT_CACHE[id(image)] = (image, variants)
    return variants


def _degrade_resolution(image: Image.Image, rng: random.Random) -> Image.Image:
    """Simulate resolution loss: with 50% probability swap the image for a
    precomputed downscaled/restored variant (25%, 40% or 50% scale,
    BILINEAR/BICUBIC)."""
    if rng.random() >= RESOLUTION_DEGRADE_PROBABILITY:
        return image
    level = rng.choice(RESOLUTION_DEGRADE_LEVELS)
    resample = rng.choice(RESOLUTION_DEGRADE_RESAMPLING)
    return _degraded_variants(image)[(level, resample)]


def _sample_size_scale(rng: random.Random) -> float:
    return max(SIZE_SCALE_MIN, min(SIZE_SCALE_MAX, rng.gauss(1.0, SIZE_SIGMA)))


def _sample_offset(rng: random.Random) -> int:
    return round(max(-POSITION_OFFSET_MAX, min(POSITION_OFFSET_MAX, rng.gauss(0.0, 3.0))))


def _sample_center(rng: random.Random) -> tuple[int, int]:
    return (
        round(max(0, min(OUTPUT_SIZE[0] - 1, rng.gauss(OUTPUT_SIZE[0] / 2, CENTER_SIGMA)))),
        round(max(0, min(OUTPUT_SIZE[1] - 1, rng.gauss(OUTPUT_SIZE[1] / 2, CENTER_SIGMA)))),
    )


def _sample_map_crop_origin(rng: random.Random, background: Image.Image) -> tuple[int, int]:
    """Sample a broad center-weighted map crop while avoiding map edges."""
    max_left = background.width - OUTPUT_SIZE[0]
    max_top = background.height - OUTPUT_SIZE[1]
    center_x = background.width / 2
    center_y = background.height / 2
    sigma_x = background.width / 5
    sigma_y = background.height / 5
    crop_center_x = max(OUTPUT_SIZE[0] / 2, min(max_left + OUTPUT_SIZE[0] / 2, rng.gauss(center_x, sigma_x)))
    crop_center_y = max(OUTPUT_SIZE[1] / 2, min(max_top + OUTPUT_SIZE[1] / 2, rng.gauss(center_y, sigma_y)))
    return (
        round(crop_center_x - OUTPUT_SIZE[0] / 2),
        round(crop_center_y - OUTPUT_SIZE[1] / 2),
    )


def _add_blue_overlay(image: Image.Image, rng: random.Random) -> dict[str, object] | None:
    """Occasionally tint the whole sample with a reference-like blue layer."""
    if rng.random() >= BLUE_OVERLAY_PROBABILITY:
        return None
    color = tuple(
        max(0, min(255, round(rng.gauss(channel, BLUE_OVERLAY_COLOR_SIGMA))))
        for channel in BLUE_OVERLAY_COLOR
    )
    alpha = max(0, min(255, round(rng.gauss(BLUE_OVERLAY_ALPHA, BLUE_OVERLAY_ALPHA_SIGMA))))
    overlay = Image.new("RGBA", image.size, (*color, alpha))
    tinted = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    image.paste(tinted)
    return {"color": list(color), "alpha": alpha}


def _sample_adjustment(rng: random.Random, bounds: tuple[float, float], mean: float, sigma: float) -> float:
    return max(bounds[0], min(bounds[1], rng.gauss(mean, sigma)))


def _adjust_color(image: Image.Image, rng: random.Random) -> dict[str, float]:
    """Apply mild independent brightness, contrast, and saturation changes."""
    brightness = _sample_adjustment(rng, BRIGHTNESS_RANGE, BRIGHTNESS_MEAN, BRIGHTNESS_SIGMA)
    contrast = _sample_adjustment(rng, CONTRAST_RANGE, CONTRAST_MEAN, CONTRAST_SIGMA)
    saturation = _sample_adjustment(rng, SATURATION_RANGE, SATURATION_MEAN, SATURATION_SIGMA)
    adjusted = ImageEnhance.Brightness(image).enhance(brightness)
    adjusted = ImageEnhance.Contrast(adjusted).enhance(contrast)
    adjusted = ImageEnhance.Color(adjusted).enhance(saturation)
    image.paste(adjusted)
    return {
        "brightness": round(brightness, 4),
        "contrast": round(contrast, 4),
        "saturation": round(saturation, 4),
    }


def _adjust_detail(image: Image.Image, rng: random.Random) -> tuple[dict[str, object], Image.Image]:
    """Randomly sharpen or blur, then apply a mild one-axis stretch."""
    if rng.random() < SHARPEN_PROBABILITY:
        amount = rng.uniform(*SHARPEN_RANGE)
        image = ImageEnhance.Sharpness(image).enhance(amount)
        detail: dict[str, object] = {"filter": "sharpen", "amount": round(amount, 4)}
    else:
        radius = rng.uniform(*BLUR_RADIUS_RANGE)
        image = image.filter(ImageFilter.GaussianBlur(radius))
        detail = {"filter": "blur", "radius": round(radius, 4)}

    direction = rng.choice(("horizontal", "vertical"))
    factor = max(STRETCH_RANGE[0], min(STRETCH_RANGE[1], rng.gauss(1.05, STRETCH_SIGMA)))
    if direction == "horizontal":
        resized = image.resize((max(1, round(image.width * factor)), image.height), Image.Resampling.BICUBIC)
    else:
        resized = image.resize((image.width, max(1, round(image.height * factor))), Image.Resampling.BICUBIC)
    if direction == "horizontal":
        left = (resized.width - image.width) // 2
        image = resized.crop((left, 0, left + image.width, image.height))
    else:
        top = (resized.height - image.height) // 2
        image = resized.crop((0, top, image.width, top + image.height))
    detail.update({"stretch_direction": direction, "stretch_factor": round(factor, 4)})
    return detail, image


def _sample_game_crop(rng: random.Random, game: Image.Image) -> tuple[Image.Image, int, int]:
    """Sample a random ``OUTPUT_SIZE`` region from a game background image."""
    max_left = max(0, game.width - OUTPUT_SIZE[0])
    max_top = max(0, game.height - OUTPUT_SIZE[1])
    left = rng.randint(0, max_left) if max_left > 0 else 0
    top = rng.randint(0, max_top) if max_top > 0 else 0
    crop = game.crop((left, top, left + OUTPUT_SIZE[0], top + OUTPUT_SIZE[1])).convert("RGB")
    if crop.size != OUTPUT_SIZE:
        crop = crop.resize(OUTPUT_SIZE, Image.Resampling.BICUBIC)
    return crop, left, top


def _blend_onto_game(
    image: Image.Image,
    games: dict[int, Image.Image],
    rng: random.Random,
) -> tuple[dict[str, object] | None, Image.Image]:
    """Occasionally overlay the semi-transparent sample onto a game crop."""
    if not games or rng.random() >= GAME_BLEND_PROBABILITY:
        return None, image
    key = rng.choice(sorted(games))
    background, left, top = _sample_game_crop(rng, games[key])
    alpha = rng.uniform(*GAME_ALPHA_RANGE)
    return {"game": key, "alpha": round(alpha, 4), "origin": [left, top]}, Image.blend(
        background, image.convert("RGB"), alpha
    )


def _choose_variant(rng: random.Random, variant_paths: dict[int, Path], has_base: bool) -> int | None:
    """Choose a variant according to the requested 50/25/25 distribution."""
    if not has_base:
        return None
    variant = rng.choices((None, 0, 1), weights=VARIANT_PROBABILITIES, k=1)[0]
    if variant is not None and variant not in variant_paths:
        raise ValueError(f"Missing assets/var/{variant:02d}.png")
    return variant


def _choose_base(
    rng: random.Random,
    base_paths: dict[int, Path],
    meta: dict[int, int],
) -> int:
    """Choose a base image so every building type is equally likely.

    A type may be backed by several base images; each type gets a total
    probability of ``1 / len(types)``, split evenly among its base images.
    """
    keys = sorted(base_paths)
    per_type = Counter(meta[key] for key in keys)
    weights = [1.0 / (len(per_type) * per_type[meta[key]]) for key in keys]
    return rng.choices(keys, weights=weights, k=1)[0]


BG_SELECTION_PROBABILITIES = (0.4, 0.05, 0.05, 0.05, 0.4, 0.05)


def _choose_background(rng: random.Random, backgrounds: dict[int, Path]) -> int:
    """Choose a map background, weighting backgrounds 0 and 4 far above the rest."""
    keys = sorted(backgrounds)
    weights = BG_SELECTION_PROBABILITIES[: len(keys)]
    return rng.choices(keys, weights=weights, k=1)[0]


def _add_other_objects(
    image: Image.Image,
    others: dict[int, Image.Image],
    rng: random.Random,
) -> tuple[list[dict[str, object]] | None, list[tuple[Image.Image, tuple[int, int]]]]:
    """Plan 0-2 random distractor objects.

    Objects flagged ``OTHER_BEFORE_BASE`` are composited now (below the POI);
    the rest are returned so the caller can draw them on top of the POI.
    """
    if not others:
        return None, []
    count = rng.choices((0, 1, 2), weights=OTHER_COUNT_PROBABILITIES, k=1)[0]
    if count == 0:
        return None, []
    keys = sorted(others)
    weights = [OTHER_SELECTION_PROBABILITIES[key] for key in keys]
    drawn: list[dict[str, object]] = []
    above: list[tuple[Image.Image, tuple[int, int]]] = []
    for key in rng.choices(keys, weights=weights, k=count):
        obj = _degrade_resolution(others[key], rng)
        scale = OTHER_BASE_SCALE[key] * _sample_size_scale(rng)
        obj = _resize_icon(obj, scale)
        # Allow the object to sit anywhere, clipping parts outside the crop.
        max_left = image.width - obj.width
        max_top = image.height - obj.height
        left = rng.randint(min(0, max_left), max(0, max_left))
        top = rng.randint(min(0, max_top), max(0, max_top))
        if OTHER_BEFORE_BASE[key]:
            image.paste(obj, (left, top), obj)
        else:
            above.append((obj, (left, top)))
        drawn.append({"other": key, "scale": round(scale, 4), "pos": [left, top]})
    return drawn, above


def _recolor_player(image: Image.Image, hue: float) -> Image.Image:
    """Recolour the saturated pixels of the (blue) player icon to ``hue`` degrees,
    leaving low-saturation outline/highlight pixels untouched."""
    array = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.0
    rgb = array[..., :3]
    high = rgb.max(axis=-1)
    low = rgb.min(axis=-1)
    sat = np.where(high > 0.0, (high - low) / np.maximum(high, 1e-6), 0.0)
    h = np.full_like(high, hue / 360.0)
    sector = h * 6.0
    f = sector - np.floor(sector)
    i = np.floor(sector).astype(np.int64) % 6
    p = high * (1.0 - sat)
    q = high * (1.0 - f * sat)
    t = high * (1.0 - (1.0 - f) * sat)
    masks = [i == k for k in range(6)]
    recoloured = np.stack(
        [
            np.select(masks, [high, q, p, p, t, high]),
            np.select(masks, [t, high, high, q, p, p]),
            np.select(masks, [p, p, t, high, high, q]),
        ],
        axis=-1,
    )
    keep = (sat < PLAYER_SATURATION_THRESHOLD)[..., None]
    rgb = np.where(keep, rgb, recoloured)
    out = np.concatenate([rgb, array[..., 3:]], axis=-1)
    return Image.fromarray((np.clip(out, 0.0, 1.0) * 255.0).astype(np.uint8), "RGBA")


def _tint_player_appearance(image: Image.Image) -> Image.Image:
    """Slightly brighten and desaturate the player icon (RGB only, alpha kept)."""
    array = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.0
    rgb = array[..., :3]
    luminance = (rgb * np.array([0.299, 0.587, 0.114], dtype=np.float32)).sum(axis=-1, keepdims=True)
    rgb = luminance + (rgb - luminance) * PLAYER_SATURATION
    rgb = np.clip(rgb * PLAYER_BRIGHTNESS, 0.0, 1.0)
    out = np.concatenate([rgb, array[..., 3:]], axis=-1)
    return Image.fromarray((out * 255.0).astype(np.uint8), "RGBA")


_PLAYER_VARIANT_CACHE: dict[int, tuple[Image.Image, dict[str, Image.Image]]] = {}


def _player_variants(player: Image.Image) -> dict[str, Image.Image]:
    """Recolour + tint the player icon per colour, cached so the expensive
    per-pixel work runs once per source icon instead of once per sample."""
    cached = _PLAYER_VARIANT_CACHE.get(id(player))
    if cached is not None and cached[0] is player:
        return cached[1]
    variants: dict[str, Image.Image] = {}
    for name in PLAYER_COLORS:
        image = _recolor_player(player, PLAYER_COLOR_HUES[name]) if name in PLAYER_COLOR_HUES else player
        variants[name] = _tint_player_appearance(image)
    _PLAYER_VARIANT_CACHE[id(player)] = (player, variants)
    return variants


def _add_player(
    image: Image.Image,
    player: Image.Image | None,
    rng: random.Random,
) -> dict[str, object] | None:
    """With 20% probability overlay a recoloured/rotated player marker on top of
    every non-global component (above the POI and the ``above`` others)."""
    if player is None or rng.random() >= PLAYER_PROBABILITY:
        return None
    color_name = rng.choice(PLAYER_COLORS)
    marker = _player_variants(player)[color_name]
    base_scale = PLAYER_BASE_SCALE * OUTPUT_SIZE[0] / max(marker.width, marker.height)
    scale = base_scale * _sample_size_scale(rng)
    marker = _resize_icon(marker, scale)
    angle = rng.uniform(0.0, 360.0)
    marker = marker.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    # Place the marker's centre somewhere in the crop but keep it away from the
    # middle so it rarely hides the central POI (parts may extend outside).
    clearance = PLAYER_CENTER_CLEARANCE * OUTPUT_SIZE[0]
    target_x, target_y = image.width / 2, image.height / 2
    for _ in range(PLAYER_POSITION_TRIES):
        center_x = rng.uniform(0.0, image.width)
        center_y = rng.uniform(0.0, image.height)
        dx = center_x - target_x
        dy = center_y - target_y
        if dx * dx + dy * dy >= clearance * clearance:
            break
    left = round(center_x - marker.width / 2)
    top = round(center_y - marker.height / 2)
    image.paste(marker, (left, top), marker)
    return {
        "color": color_name,
        "scale": round(scale, 4),
        "rotation": round(angle, 2),
        "pos": [left, top],
    }


def _compose(
    background: Image.Image,
    base: Image.Image | None,
    icon_key: int | None,
    corner: Image.Image | None,
    variant: Image.Image | None,
    variant_key: int | None,
    rng: random.Random,
    others: dict[int, Image.Image] | None = None,
) -> tuple[Image.Image, tuple[int, int], list[dict[str, object]] | None]:
    """Return a crop with the POI centered and the source crop origin."""
    left, top = _sample_map_crop_origin(rng, background)
    image = background.crop((left, top, left + OUTPUT_SIZE[0], top + OUTPUT_SIZE[1])).convert("RGBA")
    other_objects, others_above = _add_other_objects(image, others or {}, rng)

    if base is None:
        for obj, pos in others_above:
            image.paste(obj, pos, obj)
        return image.convert("RGB"), (left, top), other_objects

    base = _degrade_resolution(base, rng)
    scale = POI_ICON_SCALE[icon_key] * _sample_size_scale(rng)
    icon = _resize_icon(base, scale)

    # Keep the normal POI geometry, but grow the temporary layer for enlarged
    # base icons or variants that are larger than the normal 45x45 template.
    variant_size = None
    if variant is not None:
        variant_size = (CORNER_SIZE[0], CORNER_SIZE[1]) if variant_key == 0 else (71, 71)
    layer_size = (
        max(POI_SIZE[0], icon.width, variant_size[0] if variant_size else 0),
        max(POI_SIZE[1], icon.height, variant_size[1] if variant_size else 0),
    )
    layer = Image.new("RGBA", layer_size, (0, 0, 0, 0))
    center_x, center_y = layer.width // 2, layer.height // 2
    offset_x, offset_y = POI_ICON_OFFSET.get(icon_key, (0, 0))
    icon_pos = (center_x - icon.width // 2 + offset_x, center_y - icon.height // 2 + offset_y)
    layer.alpha_composite(icon, icon_pos)
    if variant is not None:
        # Variant 00 is corner-sized; variant 01 is fixed at 64x64.
        variant = _degrade_resolution(variant, rng)
        variant_scale = _sample_size_scale(rng)
        if variant_key == 0:
            draw_size = (
                max(1, int(CORNER_SIZE[0] * 0.75 * variant_scale)),
                max(1, int(CORNER_SIZE[1] * 0.75 * variant_scale)),
            )
        else:
            draw_size = (max(1, int(64 * variant_scale)), max(1, int(64 * variant_scale)))
        variant_img = variant.resize(draw_size, Image.Resampling.BICUBIC)
        variant_pos = (
            center_x - variant_img.width // 2,
            center_y - variant_img.height // 2,
        )
        layer.paste(variant_img, variant_pos, variant_img)
    if corner is not None:
        corner = _degrade_resolution(corner, rng)
        corner_scale = _sample_size_scale(rng)
        corner_img = _resize_icon(corner, corner_scale * CORNER_SIZE[0] / corner.width).convert("RGBA")
        corner_pos = (
            int(center_x - corner_img.width / 2 + MAP_SIZE[0] * 0.013 + _sample_offset(rng)),
            int(center_y + corner_img.height / 2 + MAP_SIZE[1] * -0.007 + _sample_offset(rng)),
        )
        layer.alpha_composite(corner_img, corner_pos)

    center_x, center_y = _sample_center(rng)
    paste_at = (center_x - layer.width // 2, center_y - layer.height // 2)
    image.paste(layer, paste_at, layer)
    for obj, pos in others_above:
        image.paste(obj, pos, obj)
    return image.convert("RGB"), (left, top), other_objects


def generate(
    assets_dir: Path,
    output_dir: Path,
    count: int,
    seed: int | None = None,
) -> None:
    rng = random.Random(seed)
    base_paths = _numbered_files(assets_dir / "base", {".png"})
    corner_paths = _numbered_files(assets_dir / "corner", {".png"})
    variant_paths = _numbered_files(assets_dir / "var", {".png"})
    bg_paths = _numbered_files(assets_dir / "bg", {".jpg", ".jpeg", ".png"})
    game_paths = _numbered_files(assets_dir / "game", {".jpg", ".jpeg", ".png"})
    other_paths = _numbered_files(assets_dir / "other", {".png"})
    player_paths = _numbered_files(assets_dir / "player", {".png"})
    meta = _read_meta(assets_dir / "base" / "meta.txt")
    missing = sorted(set(base_paths) - set(meta))
    if missing:
        raise ValueError(f"Missing base metadata for: {missing}")
    if not base_paths or not bg_paths:
        raise ValueError("assets/base and assets/bg must contain images")

    output_dir.mkdir(parents=True, exist_ok=True)
    labels_path = output_dir / "labels.jsonl"
    preview_images: list[Image.Image] = []
    with labels_path.open("w", encoding="utf-8") as labels:
        backgrounds = {key: Image.open(path).convert("RGB") for key, path in bg_paths.items()}
        games = {key: Image.open(path).convert("RGB") for key, path in game_paths.items()}
        others = {key: Image.open(path).convert("RGBA") for key, path in other_paths.items()}
        players = {key: Image.open(path).convert("RGBA") for key, path in player_paths.items()}
        for index in range(count):
            bg_key = _choose_background(rng, backgrounds)
            base_key = _choose_base(rng, base_paths, meta)
            # Empty base means empty corner. Otherwise include empty corner
            # as a real class and choose a non-empty corner independently.
            has_base = rng.random() >= NO_BASE_RATE
            selected_base = base_key if has_base else None
            has_corner = rng.random() >= NO_CORNER_RATE and has_base
            selected_corner = rng.choice([*sorted(corner_paths)]) if has_corner else None
            selected_variant = _choose_variant(rng, variant_paths, has_base)
            base_image = (
                Image.open(base_paths[base_key]).convert("RGBA") if selected_base is not None else None
            )
            corner_image = (
                Image.open(corner_paths[selected_corner]).convert("RGBA")
                if selected_corner is not None
                else None
            )
            variant_image = (
                Image.open(variant_paths[selected_variant]).convert("RGBA")
                if selected_variant is not None
                else None
            )
            icon_key = meta[selected_base] if selected_base is not None else None
            if icon_key is not None and icon_key not in POI_ICON_SCALE:
                raise ValueError(f"No POI_ICON_SCALE entry for metadata key {icon_key}")
            image, (x, y), other_objects = _compose(
                backgrounds[bg_key],
                base_image,
                icon_key,
                corner_image,
                variant_image,
                selected_variant,
                rng,
                others,
            )
            blue_overlay = _add_blue_overlay(image, rng)
            player_info = _add_player(image, players.get(0), rng)
            color_adjustment = _adjust_color(image, rng)
            detail_adjustment, image = _adjust_detail(image, rng)
            game_blend, image = _blend_onto_game(image, games, rng)
            filename = f"{index:06d}.png"
            image.save(output_dir / filename)
            if count >= 100 and index < 100:
                preview_images.append(image.copy())
            labels.write(
                json.dumps(
                    {
                        "image": filename,
                        "base": selected_base,
                        "icon_key": icon_key,
                        "construct_type": icon_key or 0,
                        "corner": selected_corner,
                        "variant": selected_variant,
                        "background": bg_key,
                        "crop_xy": [x, y],
                        "others": other_objects,
                        "player": player_info,
                        "blue_overlay": blue_overlay,
                        "color_adjustment": color_adjustment,
                        "detail_adjustment": detail_adjustment,
                        "game_blend": game_blend,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    if count >= 100:
        preview = Image.new("RGB", (OUTPUT_SIZE[0] * 10, OUTPUT_SIZE[1] * 10))
        for index, sample in enumerate(preview_images):
            preview.paste(sample, ((index % 10) * OUTPUT_SIZE[0], (index // 10) * OUTPUT_SIZE[1]))
        preview.save(output_dir / "preview_10x10.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--count", type=int, default=100)
    parser.add_argument("-o", "--output", type=Path, default=Path("generated"))
    parser.add_argument("--assets", type=Path, default=Path(__file__).parent / "assets")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    generate(args.assets, args.output, args.count, args.seed)


if __name__ == "__main__":
    main()
