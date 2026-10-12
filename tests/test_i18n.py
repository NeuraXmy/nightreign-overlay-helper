from __future__ import annotations

import string
from pathlib import Path
from typing import Any

import pytest
import yaml

from nightreign_overlay.core.i18n import FALLBACK_LANGUAGE, LANGUAGES, Translator, match_language

SRC = Path(__file__).resolve().parents[1] / "src" / "nightreign_overlay"
I18N_DIRS = [SRC / "resources" / "i18n", *sorted((SRC / "plugins").glob("*/i18n"))]
TUTORIAL_DIRS = sorted((SRC / "plugins").glob("*/tutorial"))


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("zh_CN", "zh_CN"),
        ("zh_SG", "zh_CN"),
        ("zh_HK", "zh_TW"),
        ("zh-Hant", "zh_TW"),
        ("ja", "ja_JP"),
        ("en_GB", "en_US"),
        ("fr_FR", "en_US"),
    ],
)
def test_match_language(locale: str, expected: str) -> None:
    assert match_language(locale) == expected


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
        return _flatten_raw(yaml.safe_load(f) or {})


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.mark.parametrize("directory", I18N_DIRS, ids=lambda p: str(p.relative_to(SRC)))
@pytest.mark.parametrize("language", list(LANGUAGES))
def test_translation_files_are_complete(directory: Path, language: str) -> None:
    reference = _load(directory, FALLBACK_LANGUAGE)
    table = _load(directory, language)
    assert sorted(set(reference) - set(table)) == [], "missing keys"
    assert sorted(set(table) - set(reference)) == [], "keys not present in the fallback language"
    for key, value in table.items():
        assert isinstance(value, str), f"{key} is {value!r} (quote values such as On/Off/Yes/No)"
        assert _placeholders(value) == _placeholders(reference[key]), f"placeholders differ in {key}"


@pytest.mark.parametrize("directory", TUTORIAL_DIRS, ids=lambda p: str(p.relative_to(SRC)))
def test_tutorials_exist_for_every_language(directory: Path) -> None:
    for language in LANGUAGES:
        assert (directory / f"{language}.md").is_file(), language
