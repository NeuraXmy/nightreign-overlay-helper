"""Problem description, optional image attachments, and background ZIP export."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QDesktopServices
from PyQt6.QtWidgets import QAbstractItemView, QFileDialog, QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ListWidget, MessageBoxBase, PushButton, SubtitleLabel, TextEdit

from nightreign_overlay.core.diagnostics import DiagnosticArchive, create_diagnostic_archive
from nightreign_overlay.core.i18n import tr
from nightreign_overlay.core.log import get_logger
from nightreign_overlay.core.paths import user_data_dir

log = get_logger(__name__)


class _ExportSignals(QObject):
    finished = pyqtSignal(object, str)


class _ExportTask(QRunnable):
    def __init__(self, directory: Path, destination: Path, description: str, attachments: tuple[Path, ...]):
        super().__init__()
        self.signals = _ExportSignals()
        self._arguments = directory, destination, description, attachments

    def run(self) -> None:
        try:
            result = create_diagnostic_archive(*self._arguments)
        except Exception as error:
            log.exception("Failed to export diagnostic archive")
            self.signals.finished.emit(None, str(error))
        else:
            self.signals.finished.emit(result, "")


class DiagnosticExportDialog(MessageBoxBase):
    def __init__(self, parent: QWidget, *, data_directory: Path | None = None) -> None:
        super().__init__(parent)
        self._directory = data_directory if data_directory is not None else user_data_dir()
        self._task: _ExportTask | None = None
        self._result: DiagnosticArchive | None = None
        self._attachments: list[Path] = []
        self.widget.setMinimumWidth(520)
        self.viewLayout.addWidget(SubtitleLabel(tr("settings.diagnostic_export.title"), self))
        hint = BodyLabel(tr("settings.diagnostic_export.hint"), self)
        hint.setWordWrap(True)
        self.viewLayout.addWidget(hint)
        self.descriptionEdit = TextEdit(self)
        self.descriptionEdit.setPlaceholderText(tr("settings.diagnostic_export.description"))
        self.descriptionEdit.setMinimumHeight(120)
        self.descriptionEdit.setMaximumHeight(180)
        self.viewLayout.addWidget(self.descriptionEdit)
        self.viewLayout.addWidget(BodyLabel(tr("settings.diagnostic_export.attachments"), self))
        self.attachmentList = ListWidget(self)
        self.attachmentList.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.attachmentList.setMaximumHeight(100)
        self.viewLayout.addWidget(self.attachmentList)
        buttons = QHBoxLayout()
        self.addButton = PushButton(tr("settings.diagnostic_export.add_images"), self)
        self.removeButton = PushButton(tr("settings.diagnostic_export.remove_images"), self)
        self.addButton.clicked.connect(self._add_images)
        self.removeButton.clicked.connect(self._remove_images)
        buttons.addWidget(self.addButton)
        buttons.addWidget(self.removeButton)
        buttons.addStretch()
        self.viewLayout.addLayout(buttons)
        self.statusLabel = BodyLabel("", self)
        self.statusLabel.setWordWrap(True)
        self.statusLabel.setTextFormat(Qt.TextFormat.PlainText)
        self.statusLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.viewLayout.addWidget(self.statusLabel)
        self.yesButton.setText(tr("settings.diagnostic_export.export"))
        self.cancelButton.setText(tr("settings.diagnostic_export.cancel"))

    def _add_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("settings.diagnostic_export.add_images"),
            "",
            tr("settings.diagnostic_export.image_filter"),
        )
        for value in paths:
            path = Path(value).resolve()
            if path not in self._attachments:
                self._attachments.append(path)
                self.attachmentList.addItem(str(path))

    def _remove_images(self) -> None:
        rows = sorted(
            (self.attachmentList.row(item) for item in self.attachmentList.selectedItems()), reverse=True
        )
        for row in rows:
            self.attachmentList.takeItem(row)
            self._attachments.pop(row)

    def validate(self) -> bool:
        """The standard confirm button starts export and keeps the dialog visible."""
        if self._task is not None:
            return False
        if self._result is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._result.path.parent)))
            return False
        destination = self._directory / "reports" / f"diagnostics_{datetime.now():%Y%m%d_%H%M%S_%f}.zip"
        self._task = _ExportTask(
            self._directory, destination, self.descriptionEdit.toPlainText(), tuple(self._attachments)
        )
        self._task.signals.finished.connect(self._on_finished)
        self._set_busy(True)
        self.statusLabel.setText(tr("settings.diagnostic_export.working"))
        QThreadPool.globalInstance().start(self._task)
        return False

    def _set_busy(self, busy: bool) -> None:
        self.yesButton.setEnabled(not busy)
        self.cancelButton.setEnabled(not busy)
        self.descriptionEdit.setReadOnly(busy or self._result is not None)
        for widget in (self.addButton, self.removeButton, self.attachmentList):
            widget.setEnabled(not busy and self._result is None)

    @pyqtSlot(object, str)
    def _on_finished(self, result: DiagnosticArchive | None, error: str) -> None:
        self._task = None
        self._result = result
        self._set_busy(False)
        if result is None:
            self.statusLabel.setText(tr("settings.diagnostic_export.failed", error=error))
            return
        self.statusLabel.setText(
            tr("settings.diagnostic_export.success", path=result.path, count=result.file_count)
        )
        if result.skipped:
            self.statusLabel.setText(
                self.statusLabel.text()
                + "\n"
                + tr("settings.diagnostic_export.skipped", count=len(result.skipped))
            )
        self.yesButton.setText(tr("settings.diagnostic_export.open_directory"))
        self.cancelButton.setText(tr("settings.diagnostic_export.close"))
        log.info("Diagnostic archive exported: %s (%d files)", result.path, result.file_count)

    def reject(self) -> None:
        if self._task is None:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._task is not None:
            event.ignore()
        else:
            super().closeEvent(event)
