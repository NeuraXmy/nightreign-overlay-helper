"""Lightweight YAML based translations with per-namespace tables.

Every component (the core UI and each plugin) owns a directory of ``<language>.yaml`` files. Nested keys are
flattened, so ``home: {title: ...}`` is looked up as ``"home.title"``. Lookups fall back to
:data:`FALLBACK_LANGUAGE` and finally to the key itself, which makes missing translations easy to spot.

The supported languages are discovered from the core ``resources/i18n`` directory: adding a language only
requires a new ``<language>.yaml`` there. Its top level ``meta`` section describes the language and is not
part of the translation table::

    meta:
      name: 繁體中文             # native name shown in the language selector
      locales: [zh_HK, zh_Hant]  # extra system locales mapped to this language
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from nightreign_overlay.core.log import get_logger
from nightreign_overlay.core.paths import resource_path

log = get_logger(__name__)

FALLBACK_LANGUAGE = "zh_CN"
#: Used for system locales that no shipped language covers, when available.
INTERNATIONAL_LANGUAGE = "en_US"
CORE_NAMESPACE = "core"
META_KEY = "meta"


@dataclass(frozen=True)
class LanguageInfo:
    code: str
    name: str
    locales: tuple[str, ...] = ()


def _normalize_locale(name: str) -> str:
    return name.replace("-", "_")


def discover_languages(directory: Path) -> dict[str, LanguageInfo]:
    """Read the ``meta`` section of every ``<language>.yaml`` in ``directory``.

    The fallback language is listed first, the others by language code.
    """
    found: dict[str, LanguageInfo] = {}
    for path in sorted(directory.glob("*.yaml")):
        code = path.stem
        try:
            with path.open(encoding="utf-8") as f:
                meta = (yaml.safe_load(f) or {}).get(META_KEY) or {}
        except (OSError, yaml.YAMLError, AttributeError):
            log.exception("Failed to read language metadata from %s", path)
            continue
        locales = meta.get("locales") or ()
        if isinstance(locales, str):
            locales = (locales,)
        found[code] = LanguageInfo(
            code, str(meta.get("name") or code), tuple(_normalize_locale(str(item)) for item in locales)
        )
    return dict(sorted(found.items(), key=lambda item: (item[0] != FALLBACK_LANGUAGE, item[0])))


@cache
def available_languages() -> dict[str, LanguageInfo]:
    """Languages shipped with the core UI, discovered once from ``resources/i18n``."""
    return discover_languages(resource_path("i18n"))


def language_names() -> dict[str, str]:
    """``{code: native name}`` of the supported languages, for selectors."""
    return {code: info.name for code, info in available_languages().items()}


def match_language(locale_name: str, languages: Mapping[str, LanguageInfo] | None = None) -> str:
    """Map a system locale name such as ``zh_HK`` or ``en_GB`` to a supported language.

    Order: exact code, a language's declared ``meta.locales``, a language sharing the primary language
    subtag (the fallback language first), :data:`INTERNATIONAL_LANGUAGE`, :data:`FALLBACK_LANGUAGE`.
    """
    languages = available_languages() if languages is None else languages
    name = _normalize_locale(locale_name)
    if name in languages:
        return name
    parts = name.split("_")
    # Try the most specific form first: zh_Hant_HK, then zh_Hant.
    for length in range(len(parts), 0, -1):
        candidate = "_".join(parts[:length])
        for code, info in languages.items():
            if candidate in info.locales:
                return code
    primary = parts[0]
    for code in languages:
        if code.split("_")[0] == primary:
            return code
    if INTERNATIONAL_LANGUAGE in languages:
        return INTERNATIONAL_LANGUAGE
    return FALLBACK_LANGUAGE


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
        self.language = language if language in available_languages() else FALLBACK_LANGUAGE
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
                    data = yaml.safe_load(f) or {}
                data.pop(META_KEY, None)
                tables.append(_flatten(data))
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
        for language in dict.fromkeys((self.language, FALLBACK_LANGUAGE, INTERNATIONAL_LANGUAGE)):
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
