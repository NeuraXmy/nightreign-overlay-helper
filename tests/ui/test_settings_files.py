"""Settings file card location, dialogs, cancellation, restart, and errors."""

from types import SimpleNamespace

import pytest
import yaml
from PyQt6.QtWidgets import QFileDialog, QPushButton

from nightreign_overlay.core import i18n
from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin import PluginManager
from nightreign_overlay.ui.components import MultiButtonSettingCard
from nightreign_overlay.ui.pages import settings as settings_module
from nightreign_overlay.ui.pages.settings import SettingsPage
from tests.support.paths import PROJECT_ROOT
from tests.support.qt import delete_qobjects


@pytest.fixture
def page(store, qapp, monkeypatch):
    translator = Translator("zh_CN")
    translator.load_dir("core", PROJECT_ROOT / "src/nightreign_overlay/resources/i18n")
    monkeypatch.setattr(i18n, "_translator", translator)
    manager = PluginManager(store, translator, ServiceRegistry(), EventBus())
    cfg = store.bind(AppConfig, "app")
    widget = SettingsPage(cfg, manager)
    yield widget
    delete_qobjects(widget)


def test_card_in_advanced_section_has_import_and_export_buttons(page):
    cards = page.findChildren(MultiButtonSettingCard)
    card = next(card for card in cards if card.titleLabel.text() == "管理设置文件")
    assert card.parentWidget().titleLabel.text() == i18n.tr("settings.advanced.title")
    assert [button.text() for button in card.findChildren(QPushButton)] == ["导入", "导出"]


def test_export_and_cancel(page, store, tmp_path, monkeypatch):
    path = tmp_path / "export.yaml"
    store.bind(AppConfig, "app").start_minimized.set(True)
    monkeypatch.setattr(QFileDialog, "exec", lambda *_: 1)
    monkeypatch.setattr(QFileDialog, "selectedFiles", lambda *_: [str(path)])
    monkeypatch.setattr(settings_module.InfoBar, "success", lambda *_a, **_kw: None)
    page._export_settings()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["app"]["start_minimized"] is True
    assert data["app"]["theme"] == "dark"
    monkeypatch.setattr(QFileDialog, "exec", lambda *_: 0)
    monkeypatch.setattr(store, "export_file", lambda *_: pytest.fail("export on cancel"))
    page._export_settings()


@pytest.mark.parametrize("confirmed", [False, True])
def test_import_requires_loss_warning_and_restarts_only_after_success(
    page,
    store,
    tmp_path,
    monkeypatch,
    confirmed,
):
    page._config.start_minimized.set(True)
    store.flush()
    before = store.path.read_bytes()
    path = tmp_path / "import.yaml"
    path.write_text("app: {start_minimized: false}\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: (str(path), ""))
    warnings = []

    def dialog(_title, content, _parent):
        warnings.append(content)
        return SimpleNamespace(
            yesButton=SimpleNamespace(setText=lambda *_: None),
            cancelButton=SimpleNamespace(setText=lambda *_: None),
            exec=lambda: confirmed,
        )

    monkeypatch.setattr(settings_module, "MessageBox", dialog)
    restarted = []
    page.restartRequested.connect(lambda: restarted.append(store.path.read_text(encoding="utf-8")))
    page._import_settings()
    assert len(warnings) == 1 and "当前所有设置将丢失" in warnings[0] and "立即重启" in warnings[0]
    if confirmed:
        assert len(restarted) == 1
        assert yaml.safe_load(restarted[0]) == {"app": {"start_minimized": False}}
    else:
        assert restarted == [] and store.path.read_bytes() == before


def test_invalid_import_reports_error_without_confirmation_or_restart(page, tmp_path, monkeypatch):
    path = tmp_path / "invalid.yaml"
    path.write_text("- invalid\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: (str(path), ""))
    monkeypatch.setattr(settings_module, "MessageBox", lambda *_: pytest.fail("invalid import confirmation"))
    errors = []
    monkeypatch.setattr(page, "_settings_file_error", lambda: errors.append(True))
    page.restartRequested.connect(lambda: pytest.fail("restart on invalid import"))
    page._import_settings()
    assert errors == [True]


def test_import_dialog_cancel_has_no_effect(page, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: ("", ""))
    monkeypatch.setattr(page._store, "read_import_file", lambda *_: pytest.fail("read on cancel"))
    page._import_settings()
