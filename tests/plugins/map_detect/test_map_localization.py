"""Localized map names, Chinese fallback and strings embedded in rendered images."""

from datetime import timedelta
from functools import partial
from types import SimpleNamespace

from nightreign_overlay.core import i18n
from nightreign_overlay.plugins.map_detect import localization
from nightreign_overlay.plugins.map_detect.localization import load_names, rendering_translator
from nightreign_overlay.plugins.map_detect.overlay import MapInfoOverlay, get_readable_timedelta


def test_names_fallback_by_file_id_and_blank_name(tmp_path):
    (tmp_path / "zh_CN-names.csv").write_text("id,name\n1,名字一\n2,名字二\n3,名字三\n", encoding="utf-8")
    assert load_names("missing", tmp_path) == {1: "名字一", 2: "名字二", 3: "名字三"}
    (tmp_path / "test-names.csv").write_text("id,name\n1,Test name\n2,\n", encoding="utf-8-sig")
    assert load_names("test", tmp_path) == {1: "Test name", 2: "名字二", 3: "名字三"}


def test_rendering_yaml_fallback_duration_and_crystal_legend(tmp_path, monkeypatch):
    # Synthetic translation fixture only: no additional shipped language is introduced.
    monkeypatch.setattr(i18n, "available_languages", lambda: {"zh_CN": None, "test": None})
    (tmp_path / "zh_CN.yaml").write_bytes((localization.I18N_DIR / "zh_CN.yaml").read_bytes())
    (tmp_path / "test.yaml").write_text(
        'overlay:\n  matching: "Test {spinner}"\n  legend:\n    crystal: Test legend\n'
        '  duration:\n    seconds: "Test {seconds}"\ndrawing:\n  flask: Test flask\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(localization, "I18N_DIR", tmp_path)
    translated = rendering_translator("test")
    tr = partial(translated.tr, "map_detect")
    assert tr("overlay.matching", spinner="|") == "Test |"
    assert tr("drawing.flask") == "Test flask"
    assert tr("drawing.extra_boss", name="名字") == "额外Boss:名字"
    assert get_readable_timedelta(timedelta(seconds=5), tr) == "Test 5"
    assert get_readable_timedelta(timedelta(seconds=65), tr) == "1分钟5秒"
    assert get_readable_timedelta(timedelta(seconds=3665), tr) == "1小时1分钟5秒"
    texts = []
    monkeypatch.setattr(
        "nightreign_overlay.plugins.map_detect.overlay.draw_text",
        lambda _img, _pos, text, *_args, **_kwargs: texts.append(text),
    )
    window = SimpleNamespace(_tr=tr)
    MapInfoOverlay.init_crystal_layout_imgs(window)
    assert "Test legend" in texts
    assert "地下水晶点位" in texts
    assert "额外水晶点位" in texts
