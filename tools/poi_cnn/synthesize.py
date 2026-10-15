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
from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

MAP_SIZE = (750, 750)
OUTPUT_SIZE = (64, 64)
POI_SIZE = (45, 45)
POI_ICON_SCALE = {
    30: 0.35,
    32: 0.5,
    34: 0.4,
    37: 0.4,
    38: 0.3,
    40: 0.4,
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
POI_ICON_OFFSET = {500: (0, -3), 501: (0, 3), 535: (-3, -3), 536: (0, -2)}
CORNER_SIZE = (int(MAP_SIZE[0] * 0.0195), int(MAP_SIZE[1] * 0.0195))
VARIANT_PROBABILITIES = (0.5, 0.25, 0.25)  # none, var/00, var/01
SIZE_SCALE_MIN = 0.9
SIZE_SCALE_MAX = 1.1
POSITION_OFFSET_MAX = 5
CENTER_SIGMA = OUTPUT_SIZE[0] / 6
SIZE_SIGMA = 0.033
CIRCLE_PROBABILITY = 0.1
CIRCLE_SIZE = 20
CIRCLE_COLORS = {
    "light_red": (255, 190, 190),
    "light_blue": (190, 215, 255),
    "light_green": (190, 240, 190),
}
BLUE_OVERLAY_PROBABILITY = 0.2
# Approximate the dark blue outside the outer ring in the reference map.jpg.
BLUE_OVERLAY_COLOR = (28, 47, 66)
BLUE_OVERLAY_COLOR_SIGMA = 5.0
BLUE_OVERLAY_ALPHA = 88
BLUE_OVERLAY_ALPHA_SIGMA = 10.0
BRIGHTNESS_RANGE = (0.5, 1.5)
CONTRAST_RANGE = (0.5, 1.5)
SATURATION_RANGE = (0.5, 1.5)
COLOR_ADJUST_SIGMA = 0.1
SHARPEN_PROBABILITY = 0.5
SHARPEN_RANGE = (1.15, 1.8)
BLUR_RADIUS_RANGE = (0.35, 0.5)
STRETCH_RANGE = (1.0, 1.1)
STRETCH_SIGMA = 0.03
GAME_BLEND_PROBABILITY = 0.1
GAME_ALPHA_RANGE = (0.5, 0.75)


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


def _add_random_circle(image: Image.Image, rng: random.Random) -> tuple[str, list[int]] | None:
    """Occasionally add a light circular occlusion to the final sample."""
    if rng.random() >= CIRCLE_PROBABILITY:
        return None
    color_name = rng.choice(tuple(CIRCLE_COLORS))
    left = rng.randint(0, OUTPUT_SIZE[0] - CIRCLE_SIZE)
    top = rng.randint(0, OUTPUT_SIZE[1] - CIRCLE_SIZE)
    ImageDraw.Draw(image).ellipse(
        (left, top, left + CIRCLE_SIZE - 1, top + CIRCLE_SIZE - 1),
        fill=CIRCLE_COLORS[color_name],
    )
    return color_name, [left, top, left + CIRCLE_SIZE, top + CIRCLE_SIZE]


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


def _sample_adjustment(rng: random.Random, bounds: tuple[float, float]) -> float:
    return max(bounds[0], min(bounds[1], rng.gauss(1.0, COLOR_ADJUST_SIGMA)))


def _adjust_color(image: Image.Image, rng: random.Random) -> dict[str, float]:
    """Apply mild independent brightness, contrast, and saturation changes."""
    brightness = _sample_adjustment(rng, BRIGHTNESS_RANGE)
    contrast = _sample_adjustment(rng, CONTRAST_RANGE)
    saturation = _sample_adjustment(rng, SATURATION_RANGE)
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


def _compose(
    background: Image.Image,
    base: Image.Image | None,
    icon_key: int | None,
    corner: Image.Image | None,
    variant: Image.Image | None,
    variant_key: int | None,
    rng: random.Random,
) -> tuple[Image.Image, tuple[int, int]]:
    """Return a crop with the POI centered and the source crop origin."""
    left, top = _sample_map_crop_origin(rng, background)
    image = background.crop((left, top, left + OUTPUT_SIZE[0], top + OUTPUT_SIZE[1])).convert("RGBA")

    if base is None:
        return image.convert("RGB"), (left, top)

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
    return image.convert("RGB"), (left, top)


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
        for index in range(count):
            bg_key = rng.choice(sorted(backgrounds))
            base_key = rng.choice(sorted(base_paths))
            # Empty base means empty corner. Otherwise include empty corner
            # as a real class and choose a non-empty corner independently.
            has_base = rng.random() >= 0.2
            selected_base = base_key if has_base else None
            selected_corner = rng.choice([None, *sorted(corner_paths)]) if has_base else None
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
            image, (x, y) = _compose(
                backgrounds[bg_key],
                base_image,
                icon_key,
                corner_image,
                variant_image,
                selected_variant,
                rng,
            )
            circle = _add_random_circle(image, rng)
            blue_overlay = _add_blue_overlay(image, rng)
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
                        "circle": ({"color": circle[0], "bbox": circle[1]} if circle else None),
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
