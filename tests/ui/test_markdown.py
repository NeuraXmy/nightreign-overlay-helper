"""Rendered tutorial and FAQ text must survive inline image resizing."""

from pathlib import Path

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import QApplication

from nightreign_overlay.ui.markdown import MarkdownTextBrowser, configure_markdown_browser
from tests.support.paths import PROJECT_ROOT
from tests.support.qt import delete_qobjects, process_events

RESOURCE_ROOT = PROJECT_ROOT / "src" / "nightreign_overlay"
DOCUMENTS = sorted(RESOURCE_ROOT.glob("plugins/*/tutorial/*.md")) + sorted(
    RESOURCE_ROOT.glob("resources/faq/*.md")
)


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda p: str(p.relative_to(RESOURCE_ROOT)))
def test_all_document_blocks_render_after_image_resizing(qapp: QApplication, path: Path) -> None:
    browser = MarkdownTextBrowser()
    try:
        browser.resize(850, 600)
        browser.setSource(QUrl.fromLocalFile(str(path)), QTextDocument.ResourceType.MarkdownResource)
        original_text = browser.toPlainText()
        configure_markdown_browser(browser)
        browser.show()
        for width in (850, 560, 1100, 850):
            browser.resize(width, 600)
            process_events()
            browser.verticalScrollBar().setValue(browser.verticalScrollBar().maximum())
            process_events()
            assert browser.toPlainText() == original_text
            document = browser.document()
            layout = document.documentLayout()
            block = document.begin()
            while block.isValid():
                if block.text().strip():
                    rect = layout.blockBoundingRect(block)
                    assert not rect.isEmpty(), f"Missing layout at width {width}: {block.text()!r}"
                    assert block.layout().lineCount() > 0
                block = block.next()
            cursor = QTextCursor(document)
            cursor.movePosition(QTextCursor.MoveOperation.End)
            browser.setTextCursor(cursor)
            browser.ensureCursorVisible()
            process_events()
            assert browser.viewport().rect().intersects(browser.cursorRect())
    finally:
        delete_qobjects(browser)
