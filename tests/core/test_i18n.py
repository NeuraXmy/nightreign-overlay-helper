from __future__ import annotations

import ast
import re
import string
from collections import Counter
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
DOC_FILES = sorted(path for directory in TUTORIAL_DIRS for path in directory.glob("*.md")) + sorted(
    (SRC / "resources" / "faq").glob("*.md")
)


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


def _placeholders(text: str) -> Counter[str]:
    return Counter(name for _, name, _, _ in string.Formatter().parse(text) if name)


def _translation_cases() -> list[tuple[Path, str]]:
    """Require every registered language in the core and every plugin namespace."""
    return [
        (directory, language)
        for directory in [CORE_I18N_DIR, *PLUGIN_I18N_DIRS]
        for language in available_languages()
    ]


def _literal_keys(expression: ast.expr) -> set[str]:
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return {expression.value}
    if isinstance(expression, ast.IfExp):
        return _literal_keys(expression.body) | _literal_keys(expression.orelse)
    return set()


def _plugin_source_keys(directory: Path) -> set[str]:
    """Collect literal plugin lookups; dynamic keys are exercised by plugin UI tests."""
    keys = {"plugin.name", "plugin.description"}
    for path in directory.glob("**/*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        core_aliases = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "nightreign_overlay.core.i18n"
            for alias in node.names
            if alias.name == "tr"
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            plugin_lookup = (
                isinstance(func, ast.Name) and func.id == "tr" and func.id not in core_aliases
            ) or (
                isinstance(func, ast.Attribute)
                and (
                    func.attr == "_tr"
                    or (func.attr == "tr" and ast.unparse(func.value).split(".")[-1] == "ctx")
                )
            )
            if plugin_lookup:
                keys.update(_literal_keys(node.args[0]))
    return keys


def test_shipped_languages_declare_their_name() -> None:
    assert {path.stem for path in CORE_I18N_DIR.glob("*.yaml")} == set(available_languages())
    assert next(iter(available_languages())) == FALLBACK_LANGUAGE
    for path in CORE_I18N_DIR.glob("*.yaml"):
        with path.open(encoding="utf-8") as f:
            meta = yaml.safe_load(f).get(META_KEY)
        assert isinstance(meta, dict) and isinstance(meta.get("name"), str), path.name


@pytest.mark.parametrize(
    "directory", [CORE_I18N_DIR, *PLUGIN_I18N_DIRS], ids=lambda p: str(p.relative_to(SRC))
)
def test_every_namespace_ships_all_registered_languages(directory: Path) -> None:
    assert {path.stem for path in directory.glob("*.yaml")} == set(available_languages())


@pytest.mark.parametrize("directory", PLUGIN_I18N_DIRS, ids=lambda p: str(p.relative_to(SRC)))
def test_plugin_translations_have_the_fallback_language(directory: Path) -> None:
    assert (directory / f"{FALLBACK_LANGUAGE}.yaml").is_file()


@pytest.mark.parametrize("directory", PLUGIN_I18N_DIRS, ids=lambda p: str(p.relative_to(SRC)))
def test_plugin_chinese_translations_cover_source(directory: Path) -> None:
    table = _load(directory, FALLBACK_LANGUAGE)
    # Descriptions are optional; Translator returns an empty string for absent content.
    missing = sorted(
        key for key in _plugin_source_keys(directory.parent) - table.keys() if not key.endswith(".content")
    )
    assert not missing, f"plugin source keys missing from zh_CN: {missing}"
    for key, value in table.items():
        assert isinstance(value, str) and value.strip(), f"empty or invalid zh_CN translation: {key}"


@pytest.mark.parametrize(
    ("directory", "language"),
    _translation_cases(),
    ids=lambda value: str(value.relative_to(SRC)) if isinstance(value, Path) else value,
)
def test_all_languages_match_chinese_fields_and_placeholders(directory: Path, language: str) -> None:
    assert language in available_languages(), f"{language} is not a core language"
    assert (directory / f"{language}.yaml").is_file(), f"missing {language} translation file"
    reference = _load(directory, FALLBACK_LANGUAGE)
    table = _load(directory, language)
    assert sorted(reference.keys() - table.keys()) == [], "missing Chinese reference fields"
    assert sorted(table.keys() - reference.keys()) == [], "obsolete fields absent from Chinese reference"
    for key, value in table.items():
        assert isinstance(value, str), f"{key} is {value!r} (quote values such as On/Off/Yes/No)"
        assert value.strip(), f"empty translation: {key}"
        assert _placeholders(value) == _placeholders(reference[key]), f"placeholders differ in {key}"


def test_missing_setting_description_is_optional(translations: Path) -> None:
    translator = Translator(FALLBACK_LANGUAGE)
    translator.load_dir("ns", translations)
    assert translator.tr("ns", "settings.optional.content") == ""
    assert translator.tr("ns", "settings.required.title") == "settings.required.title"


@pytest.mark.parametrize("directory", TUTORIAL_DIRS, ids=lambda p: str(p.relative_to(SRC)))
def test_tutorials_have_the_fallback_language(directory: Path) -> None:
    assert (directory / f"{FALLBACK_LANGUAGE}.md").is_file()
    for path in directory.glob("*.md"):
        assert path.stem in available_languages(), f"{path.name} is not a core language"


@pytest.mark.parametrize("path", DOC_FILES, ids=lambda path: str(path.relative_to(SRC)))
def test_documentation_resources_are_valid_utf8(path: Path) -> None:
    """Documentation must not contain encoding replacement characters."""
    text = path.read_text(encoding="utf-8")
    assert "\ufffd" not in text
    if path.stem in {"ja_JP", "zh_TW"}:
        assert any(ord(char) > 127 for char in text), f"{path} appears to have lost its non-ASCII text"
    if path.stem == "en_US":
        assert not re.search(r"\?[A-Za-z][^?\n]*\?", text), f"{path} contains replaced quoted text"
        assert not re.search(r"[A-Za-z]\?[A-Za-z]", text), f"{path} contains a replacement question mark"


@pytest.mark.parametrize(
    "path",
    sorted((PROJECT_ROOT / "docs").rglob("*.md")),
    ids=lambda p: str(p.relative_to(PROJECT_ROOT / "docs")),
)
def test_project_documents_are_readable_utf8(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "\ufffd" not in text
    assert not re.search(r"\?{4,}", text), f"{path.name} contains lost text"


@pytest.mark.parametrize(
    "key", ["updates.history_hint", "updates.auto_hint", "optional.hint", "optional.content"]
)
def test_missing_descriptions_and_hints_are_optional(translations: Path, key: str) -> None:
    translator = Translator("en_US")
    translator.load_dir("ns", translations)
    assert translator.tr("ns", key) == ""
    assert translator.tr("ns", "missing.title") == "missing.title"


def test_optional_hint_still_uses_language_fallback(translations: Path) -> None:
    path = translations / "zh_CN.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "optional_hint: 回退提示\n", encoding="utf-8")
    translator = Translator("en_US")
    translator.load_dir("ns", translations)
    assert translator.tr("ns", "optional_hint") == "回退提示"
