"""Application-owned background update actions and release dialogs."""

from __future__ import annotations

import threading
import time
from collections import deque
from html import escape
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices, QTextDocument
from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QProgressBar, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, InfoBar, PushButton, SubtitleLabel

from nightreign_overlay.core.i18n import tr
from nightreign_overlay.core.log import get_logger
from nightreign_overlay.core.updates import (
    DownloadCancellation,
    DownloadCancelledError,
    Release,
    check_releases,
    download_release,
    is_newer,
)
from nightreign_overlay.meta import APP_VERSION, GITEE_REPO, REPO_URL
from nightreign_overlay.ui.markdown import MarkdownTextBrowser, configure_markdown_browser

log = get_logger(__name__)


class ReleaseDialog(QDialog):
    downloadRequested = pyqtSignal(object)
    closed = pyqtSignal()

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)

    def reject(self) -> None:
        self.closed.emit()
        super().reject()

    def __init__(self, releases: list[Release], update: bool, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("updates.available" if update else "updates.changelog"))
        self.resize(700, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(SubtitleLabel(self.windowTitle(), self))
        self.browser = browser = MarkdownTextBrowser(self)
        browser.setOpenExternalLinks(True)
        sections = []
        for release in releases:
            body = QTextDocument()
            if release.body_is_html:
                body.setHtml(release.body)
            else:
                body.setMarkdown(release.body)
            # Normalize both formats to HTML before composing the document. Qt's
            # Markdown parser can merge a heading with a following HTML block.
            html = body.toHtml().split("<body", 1)[1].split(">", 1)[1].rsplit("</body>", 1)[0]
            sections.append(f"<h2>{escape(release.tag)}</h2>{html}")
        browser.setHtml("<hr>".join(sections))
        configure_markdown_browser(browser)
        layout.addWidget(browser, 1)
        if not update and any(release.limited_history for release in releases):
            limited = BodyLabel(tr("updates.history_limited"), self)
            limited.setWordWrap(True)
            layout.addWidget(limited)
        hint = BodyLabel(tr("updates.install_hint"), self)
        hint.setWordWrap(True)
        hint.setVisible(bool(hint.text()))
        layout.addWidget(hint)
        links = BodyLabel(
            f'<a href="{REPO_URL}/releases">GitHub</a> · '
            f'<a href="https://gitee.com/{GITEE_REPO}/releases">Gitee</a>',
            self,
        )
        links.setOpenExternalLinks(True)
        layout.addWidget(links)
        fallback = BodyLabel(tr("updates.manual_hint"), self)
        fallback.setWordWrap(True)
        fallback.setVisible(bool(fallback.text()))
        layout.addWidget(fallback)
        self.progressLabel = BodyLabel(self)
        self.progressLabel.setWordWrap(True)
        self.progressBar = QProgressBar(self)
        self.progressLabel.hide()
        self.progressBar.hide()
        layout.addWidget(self.progressLabel)
        layout.addWidget(self.progressBar)
        buttons = QHBoxLayout()
        if update:
            release = releases[0]
            self.downloadButton = PushButton(tr("updates.download", source=release.source.title()), self)
            self.downloadButton.setEnabled(bool(release.download_url))
            self.downloadButton.clicked.connect(lambda: self.downloadRequested.emit(release))
            buttons.addWidget(self.downloadButton)
        buttons.addStretch()
        close = PushButton(tr("updates.close"), self)
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)


class UpdateController(QObject):
    """Only signal emission crosses threads; all widgets and configuration stay on GUI thread."""

    checkFinished = pyqtSignal(object, str)
    downloadFinished = pyqtSignal(object, str)
    downloadProgress = pyqtSignal(object, object)
    busyChanged = pyqtSignal(bool)

    def __init__(self, window: QWidget, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._busy = False
        self._downloading = False
        self._cancellation: DownloadCancellation | None = None
        self._downloaded_bytes = 0
        self._total_bytes = 0
        self._speed_samples: deque[tuple[float, int]] = deque()
        self._speed_timer = QTimer(self)
        self._speed_timer.setInterval(500)
        self._speed_timer.timeout.connect(self._refresh_download_status)
        self._manual = False
        self._history = False
        self._closed = False
        self._dialog: ReleaseDialog | None = None
        self.checkFinished.connect(self._checked)
        self.downloadFinished.connect(self._downloaded)
        self.downloadProgress.connect(self._progress)

    def start(self, enabled: bool) -> None:
        if enabled:
            QTimer.singleShot(0, lambda: self.check(manual=False))

    def shutdown(self) -> None:
        self._closed = True
        if self._dialog:
            self._dialog.close()

    def check(self, *, manual: bool = True, history: bool = False) -> None:
        if self._closed:
            return
        # A user action during the startup probe adopts the running request.
        self._manual |= manual
        self._history |= history
        if self._busy:
            return
        self._busy = True
        self.busyChanged.emit(True)

        def work() -> None:
            try:
                result = check_releases()
            except Exception as error:
                log.warning("Update check failed: %s", error)
                self.checkFinished.emit(None, str(error))
            else:
                self.checkFinished.emit(result, "")

        threading.Thread(target=work, daemon=True).start()

    @pyqtSlot(object, str)
    def _checked(self, releases: list[Release] | None, error: str) -> None:
        self._busy = False
        self.busyChanged.emit(False)
        manual, history = self._manual, self._history
        self._manual = self._history = False
        if self._closed:
            return
        if not releases:
            if manual:
                InfoBar.error(
                    tr("updates.title"),
                    tr("updates.failed") + "\n" + error,
                    parent=self._window,
                    duration=10000,
                )
            return
        newer = is_newer(releases[0].tag, APP_VERSION)
        if history or newer:
            if self._downloading and self._dialog:
                self._window.bring_to_front()
                self._dialog.show()
                return
            if self._dialog:
                self._dialog.close()
                self._dialog.deleteLater()
            self._window.bring_to_front()
            self._dialog = ReleaseDialog(releases if history else releases[:1], not history, self._window)
            self._dialog.downloadRequested.connect(self._download)
            self._dialog.closed.connect(self._cancel_download)
            self._dialog.show()
        elif manual:
            InfoBar.success(tr("updates.title"), tr("updates.latest"), parent=self._window)

    @pyqtSlot(object)
    def _download(self, release: Release) -> None:
        if self._downloading:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self._window, tr("updates.save"), release.filename, "ZIP (*.zip)"
        )
        if not filename:
            return
        self._downloading = True
        self._downloaded_bytes = self._total_bytes = 0
        self._speed_samples.clear()
        self._speed_samples.append((time.monotonic(), 0))
        self._speed_timer.start()
        cancellation = self._cancellation = DownloadCancellation()
        if self._dialog:
            self._dialog.downloadButton.setEnabled(False)
        self._progress(0, 0)

        def work() -> None:
            started = time.monotonic()
            log.info(
                "Update download started: version=%s source=%s destination=%s",
                release.tag,
                release.source,
                filename,
            )
            try:
                path = download_release(release, Path(filename), self.downloadProgress.emit, cancellation)
            except DownloadCancelledError:
                log.info(
                    "Update download cancelled: version=%s source=%s elapsed=%.1fs",
                    release.tag,
                    release.source,
                    time.monotonic() - started,
                )
                self.downloadFinished.emit(None, "")
            except Exception as error:
                log.warning(
                    "Update download failed: version=%s source=%s elapsed=%.1fs error=%s",
                    release.tag,
                    release.source,
                    time.monotonic() - started,
                    error,
                )
                self.downloadFinished.emit(None, str(error))
            else:
                log.info(
                    "Update download completed: version=%s source=%s destination=%s elapsed=%.1fs",
                    release.tag,
                    release.source,
                    path,
                    time.monotonic() - started,
                )
                self.downloadFinished.emit(path, "")

        threading.Thread(target=work, daemon=True).start()

    @pyqtSlot()
    def _cancel_download(self) -> None:
        self._speed_timer.stop()
        if self._downloading and self._cancellation:
            self._cancellation.cancel()

    @pyqtSlot(object, object)
    def _progress(self, downloaded: int, total: int) -> None:
        if self._cancellation:
            try:
                self._cancellation.check()
            except DownloadCancelledError:
                return
        if self._closed or not self._downloading or not self._dialog:
            return
        self._downloaded_bytes, self._total_bytes = downloaded, total
        self._dialog.progressBar.show()
        self._dialog.progressLabel.show()
        self._dialog.progressBar.setRange(0, 100 if total > 0 else 0)
        if total > 0:
            self._dialog.progressBar.setValue(min(100, downloaded * 100 // total))
        self._refresh_download_status()

    @pyqtSlot()
    def _refresh_download_status(self) -> None:
        if self._closed or not self._downloading or not self._dialog:
            return
        now = time.monotonic()
        self._speed_samples.append((now, self._downloaded_bytes))
        while len(self._speed_samples) > 1 and self._speed_samples[1][0] <= now - 3:
            self._speed_samples.popleft()
        since, previous = self._speed_samples[0]
        speed = max(0, self._downloaded_bytes - previous) / max(now - since, 0.001)
        speed_text = f"{speed / 1048576:.2f} MiB/s" if speed >= 1048576 else f"{speed / 1024:.1f} KiB/s"
        if self._total_bytes > 0:
            text = tr(
                "updates.progress",
                downloaded=f"{self._downloaded_bytes / 1048576:.1f}",
                total=f"{self._total_bytes / 1048576:.1f}",
            )
        else:
            text = tr("updates.downloading")
        self._dialog.progressLabel.setText(f"{text} · {speed_text}")

    @pyqtSlot(object, str)
    def _downloaded(self, path: Path | None, error: str) -> None:
        self._downloading = False
        self._speed_timer.stop()
        cancellation, self._cancellation = self._cancellation, None
        if cancellation:
            try:
                cancellation.check()
            except DownloadCancelledError:
                if self._dialog and hasattr(self._dialog, "downloadButton"):
                    self._dialog.downloadButton.setEnabled(True)
                    self._dialog.progressBar.hide()
                    self._dialog.progressLabel.hide()
                return
        if self._closed:
            return
        if self._dialog and hasattr(self._dialog, "downloadButton"):
            self._dialog.downloadButton.setEnabled(True)
            self._dialog.progressBar.setRange(0, 100)
            if path is None:
                self._dialog.progressBar.hide()
                self._dialog.progressLabel.setText(tr("updates.download_failed"))
            else:
                self._dialog.progressBar.setValue(100)
                self._dialog.progressLabel.setText(tr("updates.saved", path=path))
        if path is None:
            InfoBar.error(
                tr("updates.title"), tr("updates.download_failed"), parent=self._window, duration=8000
            )
        else:
            InfoBar.success(
                tr("updates.title"), tr("updates.saved", path=path), parent=self._window, duration=8000
            )
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
