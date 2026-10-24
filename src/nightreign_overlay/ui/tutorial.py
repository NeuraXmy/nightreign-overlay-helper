"""Single-document tutorial rendering with collapsible Markdown sections."""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QTextCharFormat, QTextCursor, QTextDocument
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import isDarkTheme, qconfig

from nightreign_overlay.core.i18n import tr
from nightreign_overlay.core.log import get_logger
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.ui.markdown import MarkdownTextBrowser, configure_markdown_browser

log = get_logger(__name__)
_COLLAPSE = re.compile(r"^:::collapse(?:\s+(.*?))?\s*$")


class TutorialWindowApi:
    def open(self, route: str, parent: QWidget | None = None) -> bool:
        raise NotImplementedError


def _parse(text: str) -> list[tuple[str, str, str | None]]:
    sections: list[tuple[str, str, str | None]] = []
    normal: list[str] = []
    title: str | None = None
    body: list[str] = []
    for line in text.splitlines(keepends=True):
        match = _COLLAPSE.match(line.rstrip("\r\n"))
        if match and title is None:
            if normal:
                sections.append(("markdown", "".join(normal), None))
                normal.clear()
            title = match.group(1) or ""
        elif title is not None and line.rstrip("\r\n").strip() == ":::":
            sections.append(("collapse", "".join(body), title))
            title, body = None, []
        elif title is not None:
            body.append(line)
        else:
            normal.append(line)
    if title is not None:
        normal.extend([f":::collapse {title}\n", *body])
    if normal:
        sections.append(("markdown", "".join(normal), None))
    return sections


def _body_html(markdown: str) -> str:
    document = QTextDocument()
    document.setMarkdown(markdown)
    html = document.toHtml()
    body = html.split("<body", 1)[1].split(">", 1)[1].rsplit("</body>", 1)[0]
    link = "#b8ddff" if isDarkTheme() else "#0067c0"
    return re.sub(
        r'<a href="(app://tutorial/[^"]+)">',
        f'<a style="color: {link}; font-size: 90%;" href="\\1">',
        body,
    )


class TutorialBrowser(MarkdownTextBrowser):
    def __init__(self, services: ServiceRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._sections: list[tuple[str, str, str | None]] = []
        self._expanded: set[int] = set()
        self._base_url = QUrl()
        self._source_url = QUrl()
        self.setOpenLinks(False)
        self.setOpenExternalLinks(True)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.anchorClicked.connect(self._link_clicked)
        qconfig.themeChangedFinished.connect(self._refresh_theme)

    def load(self, path: Path) -> None:
        self._base_url = QUrl.fromLocalFile(str(path.parent) + "/")
        self._source_url = QUrl.fromLocalFile(str(path))
        self._sections = _parse(path.read_text(encoding="utf-8"))
        self._expanded.clear()
        self._render()

    def _render(self, *, preserve_scroll: bool = False) -> None:
        scroll_x = self.horizontalScrollBar().value() if preserve_scroll else 0
        scroll_y = self.verticalScrollBar().value() if preserve_scroll else 0
        chunks: list[str] = []
        for index, (kind, content, title) in enumerate(self._sections):
            if kind == "markdown":
                chunks.append(_body_html(content))
                continue
            expanded = index in self._expanded
            arrow = "▼" if expanded else "▶"
            link = "#b8ddff" if isDarkTheme() else "#0067c0"
            action = tr("tutorial.click_collapse" if expanded else "tutorial.click_expand", title=title or "")
            label = f"{arrow} {action}"
            body_row = (
                f'<tr><td class="tutorial-collapse-body">{_body_html(content)}</td></tr>' if expanded else ""
            )
            chunks.append(
                '<table class="tutorial-collapse" width="100%" border="1" '
                'cellpadding="10" cellspacing="0">'
                f'<tr><td><a style="color: {link}; font-size: 90%;" href="app://collapse/{index}">{label}</a></td></tr>'
                + body_row
                + "</table>"
            )
        self.setHtml(
            "<html><head><style>" + self._css() + "</style></head><body>" + "".join(chunks) + "</body></html>"
        )
        self.document().setBaseUrl(self._base_url)
        configure_markdown_browser(self)
        self._apply_link_formats()
        if preserve_scroll:
            QTimer.singleShot(
                0,
                lambda: (
                    self.horizontalScrollBar().setValue(scroll_x),
                    self.verticalScrollBar().setValue(scroll_y),
                ),
            )

    def source(self) -> QUrl:
        return self._source_url

    def _refresh_theme(self) -> None:
        if self._sections:
            self._render()

    def _apply_link_formats(self) -> None:
        link_color = "#3fa7ff" if isDarkTheme() else "#006dcc"
        collapse_color = "#d7d7d7" if isDarkTheme() else "#404040"
        base_size = self.font().pointSizeF()
        if base_size <= 0:
            base_size = 10.0
        document = self.document()
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.charFormat().isAnchor():
                    format_ = QTextCharFormat(fragment.charFormat())
                    is_collapse = QUrl(fragment.charFormat().anchorHref()).host() == "collapse"
                    format_.setForeground(QColor(collapse_color if is_collapse else link_color))
                    format_.setFontPointSize(base_size * 1.15)
                    cursor = QTextCursor(document)
                    cursor.setPosition(fragment.position())
                    cursor.movePosition(
                        QTextCursor.MoveOperation.NextCharacter,
                        QTextCursor.MoveMode.KeepAnchor,
                        fragment.length(),
                    )
                    cursor.setCharFormat(format_)
                iterator += 1
            block = block.next()

    def _link_clicked(self, url: QUrl) -> None:
        if url.scheme() == "app" and url.host() == "collapse":
            try:
                index = int(url.path().strip("/"))
            except ValueError:
                return
            if 0 <= index < len(self._sections):
                self._expanded.symmetric_difference_update({index})
                self._render(preserve_scroll=True)
            return
        if url.scheme() == "app" and url.host() == "tutorial":
            route = url.path().lstrip("/")
            service = self._services.get(TutorialWindowApi)
            if service is None or not service.open(route, self.window()):
                log.warning("Tutorial route unavailable: %s", route)
            return
        QDesktopServices.openUrl(url)

    @staticmethod
    def _css() -> str:
        link = "#b8ddff" if isDarkTheme() else "#0067c0"
        border = "#626262" if isDarkTheme() else "#c8c8c8"
        return (
            f"a {{ color: {link}; font-size: 1em; }} "
            f".tutorial-collapse {{ margin: 10px 0; border-color: {border}; }} "
            ".tutorial-collapse-title { font-weight: normal; } "
            f".tutorial-collapse-body {{ border-color: {border}; }}"
        )


def create_tutorial_browser(
    services: ServiceRegistry, path: Path, parent: QWidget | None = None
) -> TutorialBrowser:
    browser = TutorialBrowser(services, parent)
    browser.load(path)
    return browser
