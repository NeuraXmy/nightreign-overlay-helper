from __future__ import annotations

import string
from pathlib import Path
from typing import Any

import pytest
import yaml

from nightreign_overlay.core.i18n import (
    FALLBACK_LANGUAGE,
    META_KEY,
    LanguageInfo,
    Translator,
    available_languages,
    discover_languages,
    match_language,
)
from tests.support.paths import PROJECT_ROOT

SRC = PROJECT_ROOT / "src" / "nightreign_overlay"
CORE_I18N_DIR = SRC / "resources" / "i18n"
PLUGIN_I18N_DIRS = sorted((SRC / "plugins").glob("*/i18n"))
TUTORIAL_DIRS = sorted((SRC / "plugins").glob("*/tutorial"))


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("zh_CN", "zh_CN"),
        ("zh_SG", "zh_CN"),
        ("zh_HK", "zh_TW"),
        ("zh-Hant", "zh_TW"),
        ("zh_Hant_HK", "zh_TW"),
        ("ja", "ja_JP"),
        ("en_GB", "en_US"),
        ("fr_FR", "en_US"),
    ],
)
def test_match_language(locale: str, expected: str) -> None:
    assert match_language(locale) == expected


def test_languages_are_discovered_from_files(tmp_path: Path) -> None:
    (tmp_path / "zh_CN.yaml").write_text("meta:\n  name: 简体中文\ngreeting: 你好\n", encoding="utf-8")
    (tmp_path / "ko_KR.yaml").write_text(
        "meta:\n  name: 한국어\n  locales: [ko-KP]\ngreeting: 안녕\n", encoding="utf-8"
    )
    (tmp_path / "de_DE.yaml").write_text("greeting: Hallo\n", encoding="utf-8")
    languages = discover_languages(tmp_path)
    # The fallback language comes first, a missing name falls back to the code.
    assert list(languages) == ["zh_CN", "de_DE", "ko_KR"]
    assert languages["ko_KR"] == LanguageInfo("ko_KR", "한국어", ("ko_KP",))
    assert languages["de_DE"].name == "de_DE"

    assert match_language("ko_KP", languages) == "ko_KR"
    assert match_language("de_AT", languages) == "de_DE"
    # Without an international language, unknown locales use the fallback language.
    assert match_language("fr_FR", languages) == FALLBACK_LANGUAGE


def test_meta_section_is_not_a_translation(tmp_path: Path) -> None:
    (tmp_path / "zh_CN.yaml").write_text("meta:\n  name: 简体中文\ngreeting: 你好\n", encoding="utf-8")
    translator = Translator(FALLBACK_LANGUAGE)
    translator.load_dir("ns", tmp_path)
    assert translator.tr("ns", "meta.name") == "meta.name"
    assert translator.tr("ns", "greeting") == "你好"


@pytest.fixture
def translations(tmp_path: Path) -> Path:
    (tmp_path / "zh_CN.yaml").write_text(
        "greeting: 你好\nnested:\n  only_fallback: 回退\nfmt: '{name} 你好'\n", encoding="utf-8"
    )
    (tmp_path / "en_US.yaml").write_text("greeting: Hello\nfmt: 'Hello {name}'\n", encoding="utf-8")
    return tmp_path


def test_lookup_and_fallback(translations: Path) -> None:
    translator = Translator("en_US")
    translator.load_dir("ns", translations)
    assert translator.tr("ns", "greeting") == "Hello"
    assert translator.tr("ns", "nested.only_fallback") == "回退"
    assert translator.tr("ns", "missing.key") == "missing.key"
    assert translator.tr("other", "greeting") == "greeting"


def test_formatting(translations: Path) -> None:
    translator = Translator("en_US")
    translator.load_dir("ns", translations)
    assert translator.tr("ns", "fmt", name="Tarnished") == "Hello Tarnished"
    # Missing placeholders return the raw text instead of raising.
    assert translator.tr("ns", "fmt", other=1) == "Hello {name}"


def test_unknown_language_uses_fallback() -> None:
    assert Translator("xx_XX").language == FALLBACK_LANGUAGE


def test_localized_file(tmp_path: Path) -> None:
    (tmp_path / "zh_CN.md").write_text("zh", encoding="utf-8")
    (tmp_path / "ja_JP.md").write_text("ja", encoding="utf-8")
    assert Translator("ja_JP").localized_file(tmp_path, ".md") == tmp_path / "ja_JP.md"
    assert Translator("en_US").localized_file(tmp_path, ".md") == tmp_path / "zh_CN.md"
    assert Translator("en_US").localized_file(tmp_path / "missing", ".md") is None


# -- shipped resources --------------------------------------------------------------------------


def _flatten_raw(data: dict[Any, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        assert isinstance(key, str), f"non-string key {prefix}{key!r} (quote YAML keys such as on/off/yes/no)"
        if isinstance(value, dict):
            result.update(_flatten_raw(value, f"{prefix}{key}."))
        else:
            result[f"{prefix}{key}"] = value
    return result


def _load(directory: Path, language: str) -> dict[str, Any]:
    with (directory / f"{language}.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.pop(META_KEY, None)
    return _flatten_raw(data)


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _translation_cases() -> list[tuple[Path, str]]:
    """Core files must exist for every language; plugin files are optional and fall back to zh_CN."""
    cases = [(CORE_I18N_DIR, language) for language in available_languages()]
    for directory in PLUGIN_I18N_DIRS:
        cases += [(directory, path.stem) for path in sorted(directory.glob("*.yaml"))]
    return cases


def test_shipped_languages_declare_their_name() -> None:
    assert {path.stem for path in CORE_I18N_DIR.glob("*.yaml")} == set(available_languages())
    assert next(iter(available_languages())) == FALLBACK_LANGUAGE
    for path in CORE_I18N_DIR.glob("*.yaml"):
        with path.open(encoding="utf-8") as f:
            meta = yaml.safe_load(f).get(META_KEY)
        assert isinstance(meta, dict) and isinstance(meta.get("name"), str), path.name


@pytest.mark.parametrize("directory", PLUGIN_I18N_DIRS, ids=lambda p: str(p.relative_to(SRC)))
def test_plugin_translations_have_the_fallback_language(directory: Path) -> None:
    assert (directory / f"{FALLBACK_LANGUAGE}.yaml").is_file()


@pytest.mark.parametrize(
    ("directory", "language"),
    _translation_cases(),
    ids=lambda value: str(value.relative_to(SRC)) if isinstance(value, Path) else value,
)
def test_translation_files_are_complete(directory: Path, language: str) -> None:
    assert language in available_languages(), f"{language} is not a core language"
    reference = _load(directory, FALLBACK_LANGUAGE)
    table = _load(directory, language)
    assert sorted(set(reference) - set(table)) == [], "missing keys"
    assert sorted(set(table) - set(reference)) == [], "keys not present in the fallback language"
    for key, value in table.items():
        assert isinstance(value, str), f"{key} is {value!r} (quote values such as On/Off/Yes/No)"
        assert _placeholders(value) == _placeholders(reference[key]), f"placeholders differ in {key}"


@pytest.mark.parametrize("directory", TUTORIAL_DIRS, ids=lambda p: str(p.relative_to(SRC)))
def test_tutorials_have_the_fallback_language(directory: Path) -> None:
    assert (directory / f"{FALLBACK_LANGUAGE}.md").is_file()
    for path in directory.glob("*.md"):
        assert path.stem in available_languages(), f"{path.name} is not a core language"
