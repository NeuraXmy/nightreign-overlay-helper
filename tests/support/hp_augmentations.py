"""Deterministic full-frame Pillow transforms shared by HP robustness evaluations."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageEnhance, ImageFilter


@dataclass(frozen=True)
class Augmentation:
    kind: str
    value: float | None = None

    @property
    def name(self) -> str:
        return self.kind if self.value is None else f"{self.kind}_{self.value:g}"

    def apply(self, image: Image.Image) -> Image.Image:
        """Transform the entire RGB crop before the detector selects its middle row."""
        enhancers = {
            "brightness": ImageEnhance.Brightness,
            "saturation": ImageEnhance.Color,
            "contrast": ImageEnhance.Contrast,
            "sharpness": ImageEnhance.Sharpness,
        }
        if self.kind in enhancers:
            return enhancers[self.kind](image).enhance(self.value)
        if self.kind == "blur":
            return image.filter(ImageFilter.GaussianBlur(self.value))
        if self.kind == "gamma":
            return image.point([round(255 * (v / 255) ** self.value) for v in range(256)] * 3)
        if self.kind == "scale":
            return image.resize(
                (round(image.width * self.value), round(image.height * self.value)),
                Image.Resampling.LANCZOS,
            )
        if self.kind == "bright_combination":
            image = ImageEnhance.Brightness(image).enhance(1.6)
            image = ImageEnhance.Color(image).enhance(0.3)
            return ImageEnhance.Contrast(image).enhance(1.8).filter(ImageFilter.GaussianBlur(0.8))
        if self.kind == "dark_combination":
            image = ImageEnhance.Brightness(image).enhance(0.4)
            image = ImageEnhance.Color(image).enhance(2.5)
            return ImageEnhance.Sharpness(image).enhance(4)
        if self.kind == "original":
            return image
        raise ValueError(f"Unknown augmentation: {self.kind}")


def augmentations() -> list[Augmentation]:
    """The same 32 variants documented for the original twelve still images."""
    groups = {
        "brightness": (0.35, 0.6, 1.4, 1.8, 2.5),
        "saturation": (0, 0.2, 0.5, 2, 4),
        "contrast": (0.25, 0.5, 1.5, 2.5),
        "sharpness": (0, 3, 6),
        "blur": (0.5, 1, 2, 4),
        "gamma": (0.5, 0.75, 1.5, 2.2),
        "scale": (0.5, 0.75, 1.25, 1.5, 2),
    }
    return [Augmentation(kind, value) for kind, values in groups.items() for value in values] + [
        Augmentation("bright_combination"),
        Augmentation("dark_combination"),
    ]
