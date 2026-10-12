"""Lightweight YAML based translations with per-namespace tables.

Every component (the core UI and each plugin) owns a directory of ``<language>.yaml`` files. Nested keys are
flattened, so ``home: {title: ...}`` is looked up as ``"home.title"``. Lookups fall back to
:data:`FALLBACK_LANGUAGE` and finally to the key itself, which makes missing translations easy to spot.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from nightreign_overlay.core.log import get_logger

log = get_logger(__name__)

#: Supported languages, displayed with their native names.
LANGUAGES: dict[str, str] = {
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
    "en_US": "English",
    "ja_JP": "日本語",
}
FALLBACK_LANGUAGE = "zh_CN"
CORE_NAMESPACE = "core"


def match_language(locale_name: str) -> str:
    """Map a system locale name such as ``zh_HK`` or ``en_GB`` to a supported language."""
    if locale_name in LANGUAGES:
        return locale_name
    lang, _, region = locale_name.replace("-", "_").partition("_")
    if lang == "zh":
        return "zh_TW" if region in ("TW", "HK", "MO", "Hant") else "zh_CN"
    if lang == "ja":
        return "ja_JP"
    return "en_US"


def _flatten(data: Mapping[str, Any], prefix: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in data.items():
        full_key = f"{prefix}{key}"
        if isinstance(value, Mapping):
            result.update(_flatten(value, f"{full_key}."))
        else:
            result[full_key] = str(value)
    return result


class Translator:
    def __init__(self, language: str) -> None:
        self.language = language if language in LANGUAGES else FALLBACK_LANGUAGE
        self._tables: dict[str, list[dict[str, str]]] = {}

    def load_dir(self, namespace: str, directory: Path) -> None:
        """Load translations of ``namespace`` from ``directory/<language>.yaml`` (plus the fallback)."""
        tables = []
        for language in dict.fromkeys((self.language, FALLBACK_LANGUAGE)):
            path = directory / f"{language}.yaml"
            if not path.exists():
                continue
            try:
                with path.open(encoding="utf-8") as f:
                    tables.append(_flatten(yaml.safe_load(f) or {}))
            except (OSError, yaml.YAMLError):
                log.exception("Failed to load translations from %s", path)
        self._tables[namespace] = tables

    def tr(self, namespace: str, key: str, **kwargs: Any) -> str:
        text = next((table[key] for table in self._tables.get(namespace, ()) if key in table), None)
        if text is None:
            log.debug("Missing translation %s:%s", namespace, key)
            return key
        if not kwargs:
            return text
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            log.warning("Bad placeholders in translation %s:%s", namespace, key)
            return text

    def localized_file(self, directory: Path, suffix: str) -> Path | None:
        """Find ``directory/<language><suffix>`` following the fallback chain (used for tutorials)."""
        for language in (self.language, FALLBACK_LANGUAGE, "en_US"):
            path = directory / f"{language}{suffix}"
            if path.exists():
                return path
        return None


_translator = Translator(FALLBACK_LANGUAGE)


def install(translator: Translator) -> None:
    """Make ``translator`` the one used by :func:`tr`."""
    global _translator
    _translator = translator


def translator() -> Translator:
    return _translator


def tr(key: str, **kwargs: Any) -> str:
    """Translate a core UI string."""
    return _translator.tr(CORE_NAMESPACE, key, **kwargs)
