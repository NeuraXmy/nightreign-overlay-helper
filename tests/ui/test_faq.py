"""FAQ Markdown resources and the shared page banner."""

import gc
from pathlib import Path

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QImage, QTextDocument
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import SettingCard

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.game_window import GameWindowMonitor
from nightreign_overlay.core.i18n import Translator, install
from nightreign_overlay.core.paths import resource_path
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin import PluginManager
from nightreign_overlay.ui.overlay import OverlayManager
from nightreign_overlay.ui.pages import AboutPage, HomePage, faq
from nightreign_overlay.ui.pages.home import Banner
from tests.support.platform import FakeBackend
from tests.support.qt import delete_qobjects, process_events


def test_faq_resolves_markdown_and_relative_images_with_language_fallback(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    image = QImage(16, 12, QImage.Format.Format_RGB32)
    image.fill(0x123456)
    assert image.save(str(images / "example.png"))
    source = tmp_path / "zh_CN.md"
    source.write_text("## 示例问题\n\n说明文字。\n\n![示意图](images/example.png)\n", encoding="utf-8")
    monkeypatch.setattr(faq, "resource_path", lambda *_parts: tmp_path)
    monkeypatch.setattr(faq, "translator", lambda: Translator("ja_JP"))

    page = faq.FaqPage()
    try:
        assert Path(page.browser.source().toLocalFile()).resolve() == source.resolve()
        assert "示例问题" in page.browser.toPlainText()
        loaded = page.browser.document().resource(
            QTextDocument.ResourceType.ImageResource, QUrl("images/example.png")
        )
        assert loaded is not None
        assert not loaded.isNull()
        assert loaded.size() == image.size()
        assert page.browser.openExternalLinks()
    finally:
        delete_qobjects(page)


def test_about_page_contains_screenshot_only_security_statement(qapp: QApplication) -> None:
    translator = Translator("zh_CN")
    translator.load_dir("core", resource_path("i18n"))
    install(translator)
    page = AboutPage()
    try:
        cards = page.findChildren(SettingCard)
        security = next(card for card in cards if card.titleLabel.text() == "安全性声明")
        assert "截图" in security.contentLabel.text()
        assert "不读写任何游戏进程内存" in security.contentLabel.text()
        assert "官方联机模式" in security.contentLabel.text()
    finally:
        delete_qobjects(page)


def test_packaged_faq_and_shared_compact_banners(qapp: QApplication, store: ConfigStore) -> None:
    config = store.bind(AppConfig, "app")
    events = EventBus()
    plugins = PluginManager(store, Translator("zh_CN"), ServiceRegistry(), events)
    backend = FakeBackend()
    monitor = GameWindowMonitor(backend, events)
    overlays = OverlayManager(backend, config, monitor)
    pages = (HomePage(config, plugins, overlays, monitor), AboutPage(), faq.FaqPage())
    try:
        assert "识别错误，识别不准" in pages[2].browser.toPlainText()
        for page in pages[:2]:
            banner = page.findChild(Banner)
            assert banner is not None
            assert banner.height() == round(168 * 0.6)
            assert not banner.grab().isNull()
    finally:
        delete_qobjects(*pages, overlays, monitor, plugins)


def test_faq_teardown_survives_collection_before_next_event_loop(qapp: QApplication) -> None:
    destroyed = []

    def create_and_dispose() -> None:
        page = faq.FaqPage()
        page.destroyed.connect(lambda: destroyed.append("page"))
        page.browser.destroyed.connect(lambda: destroyed.append("browser"))
        delete_qobjects(page)

    # Match a completed test returning before the next test starts a nested Qt event loop.
    create_and_dispose()
    gc.collect()
    process_events()
    assert sorted(destroyed) == ["browser", "page"]
