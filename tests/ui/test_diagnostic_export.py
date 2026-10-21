"""About entry and the real background export dialog's success/retry flow."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from PIL import Image
from PyQt6.QtCore import QElapsedTimer, QThread
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import PushSettingCard

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.ui.components import diagnostic_export
from nightreign_overlay.ui.pages import about, settings


def _wait_for_export(qapp, dialog):
    # An immediate validation failure can emit before a QSignalSpy is connected.
    # Wait for the GUI to process completion instead of relying on worker speed.
    deadline = QElapsedTimer()
    deadline.start()
    while dialog._task is not None and deadline.elapsed() < 5000:
        qapp.processEvents()
        QTest.qWait(5)
    assert dialog._task is None


def test_dialog_exports_off_the_gui_thread_and_prevents_duplicate_submissions(qapp, tmp_path, monkeypatch):
    parent = QWidget()
    parent.resize(900, 800)
    parent.show()
    dialog = diagnostic_export.DiagnosticExportDialog(parent, data_directory=tmp_path)
    dialog.descriptionEdit.setPlainText("测试描述")
    original_export = diagnostic_export.create_diagnostic_archive
    started, release = threading.Event(), threading.Event()
    worker_threads = []

    def export(*args):
        worker_threads.append(QThread.currentThread())
        started.set()
        assert release.wait(5), "Test did not release the worker"
        return original_export(*args)

    monkeypatch.setattr(diagnostic_export, "create_diagnostic_archive", export)
    dialog.show()
    qapp.processEvents()
    try:
        dialog.yesButton.click()
        task = dialog._task
        spy = QSignalSpy(task.signals.finished)
        assert started.wait(2)
        assert worker_threads[0] != qapp.thread()
        assert not dialog.yesButton.isEnabled()
        assert not dialog.cancelButton.isEnabled()
        assert dialog.descriptionEdit.isReadOnly()
        assert dialog.validate() is False
        assert dialog._task is task
        dialog.reject()
        assert dialog.isVisible()
    finally:
        release.set()
    assert spy.wait(5000)
    qapp.processEvents()
    assert dialog._task is None
    assert dialog._result.path.is_file()
    assert dialog.yesButton.isEnabled()
    assert dialog.cancelButton.isEnabled()
    with ZipFile(dialog._result.path) as archive:
        assert archive.read("problem.txt").decode("utf-8") == "测试描述"
    opened = []
    monkeypatch.setattr(diagnostic_export.QDesktopServices, "openUrl", lambda url: opened.append(url))
    dialog.yesButton.click()
    assert Path(opened[0].toLocalFile()) == dialog._result.path.parent
    assert len(list((tmp_path / "reports").glob("*.zip"))) == 1
    dialog.close()
    parent.close()


def test_attachment_dedup_removal_and_failed_export_can_be_retried(qapp, tmp_path, monkeypatch):
    parent = QWidget()
    parent.resize(900, 800)
    dialog = diagnostic_export.DiagnosticExportDialog(parent, data_directory=tmp_path)
    first, second = tmp_path / "one.png", tmp_path / "two.png"
    for path in (first, second):
        Image.new("RGB", (4, 4)).save(path)
    monkeypatch.setattr(
        diagnostic_export.QFileDialog,
        "getOpenFileNames",
        lambda *args: ([str(first), str(first), str(second)], ""),
    )
    dialog.addButton.click()
    assert dialog.attachmentList.count() == 2
    dialog.attachmentList.item(1).setSelected(True)
    dialog.removeButton.click()
    assert dialog._attachments == [first]
    first.unlink()
    dialog.yesButton.click()
    _wait_for_export(qapp, dialog)
    assert dialog._result is None
    assert dialog._task is None
    assert dialog.yesButton.isEnabled()
    assert dialog.addButton.isEnabled()
    assert not dialog.descriptionEdit.isReadOnly()
    assert dialog.statusLabel.text()
    dialog.attachmentList.item(0).setSelected(True)
    dialog.removeButton.click()
    dialog.yesButton.click()
    _wait_for_export(qapp, dialog)
    assert dialog._result.path.exists()
    dialog.close()
    parent.close()


def test_only_about_button_opens_export_dialog(store, qapp, monkeypatch):
    opened = []

    class Dialog:
        def __init__(self, parent):
            opened.append(parent)

        def exec(self):
            opened.append("exec")

        def deleteLater(self):
            opened.append("delete")

    monkeypatch.setattr(about, "DiagnosticExportDialog", Dialog)
    settings_page = settings.SettingsPage(
        store.bind(AppConfig, "app"), SimpleNamespace(records=lambda: [], config_store=store)
    )
    assert not hasattr(settings_page, "diagnosticExportCard")
    page = about.AboutPage(store.bind(AppConfig, "app"))
    page.findChild(PushSettingCard).clicked.emit()
    assert opened == [page.window(), "exec", "delete"]
