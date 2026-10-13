"""Map rendering translations and per-ID Chinese fallback for localized names."""

from __future__ import annotations

import csv
from pathlib import Path

from nightreign_overlay.core.i18n import FALLBACK_LANGUAGE, Translator, translator

I18N_DIR = Path(__file__).parent / "i18n"


def rendering_translator(language: str | None = None) -> Translator:
    localized = Translator(language or translator().language)
    localized.load_dir("map_detect", I18N_DIR)
    return localized


def load_names(language: str, directory: Path = I18N_DIR) -> dict[int, str]:
    names: dict[int, str] = {}
    for code in dict.fromkeys((FALLBACK_LANGUAGE, language)):
        path = directory / f"{code}-names.csv"
        if not path.exists() and code != FALLBACK_LANGUAGE:
            continue
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                name = row["name"]
                if name and name.strip():
                    names[int(row["id"])] = name
    return names
