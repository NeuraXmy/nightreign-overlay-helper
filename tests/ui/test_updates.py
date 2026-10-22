"""Update controller foreground feedback and silent automatic checks."""

import pytest
from PyQt6.QtWidgets import QWidget

from nightreign_overlay.core import i18n
from nightreign_overlay.core.paths import resource_path
from nightreign_overlay.ui.components import updates
from tests.support.qt import delete_qobjects


class Window(QWidget):
    def bring_to_front(self):
        self.show()


def test_automatic_failure_and_latest_are_silent(qapp, monkeypatch):
    window = Window()
    controller = updates.UpdateController(window)
    messages = []
    monkeypatch.setattr(updates.InfoBar, "error", lambda *a, **k: messages.append("error"))
    monkeypatch.setattr(updates.InfoBar, "success", lambda *a, **k: messages.append("success"))
    controller._checked(None, "offline")
    release = updates.Release("v1.0.1", "notes", "github", "", "runtime.zip")
    controller._checked([release], "")
    assert not messages
    controller._manual = True
    controller._checked(None, "offline")
    assert messages == ["error"]
    delete_qobjects(controller, window)


@pytest.mark.parametrize("source,label", [("gitee", "Gitee"), ("cnb", "CNB")])
def test_new_version_shows_notes_and_download_source(qapp, monkeypatch, source, label):
    translator = i18n.Translator("en_US")
    translator.load_dir(i18n.CORE_NAMESPACE, resource_path("i18n"))
    monkeypatch.setattr(i18n, "_translator", translator)
    monkeypatch.setattr(updates, "APP_VERSION", "1.0.1")
    window = Window()
    controller = updates.UpdateController(window)
    release = updates.Release("v1.0.2", "Release details", source, "https://example.com/a.zip", "a.zip")
    controller._checked([release], "")
    assert controller._dialog.isVisible()
    assert controller._dialog.downloadButton.isEnabled()
    assert label in controller._dialog.downloadButton.text()
    assert "cnb.cool" in " ".join(
        label.text() for label in controller._dialog.findChildren(updates.BodyLabel)
    )
    controller.shutdown()
    controller._checked([release], "")
    assert not controller._dialog.isVisible()
    delete_qobjects(controller, window)


def test_check_runs_in_background_and_delivers_result_on_gui_thread(qapp, monkeypatch):
    import threading
    import time

    from PyQt6.QtCore import QCoreApplication, QEvent, QThread

    entered = threading.Event()
    resume = threading.Event()
    worker_threads = []
    gui_threads = []

    def check():
        worker_threads.append(threading.get_ident())
        entered.set()
        assert resume.wait(2)
        return [updates.Release("v1.0.1", "notes", "github", "", "runtime.zip")]

    monkeypatch.setattr(updates, "check_releases", check)
    monkeypatch.setattr(
        updates.InfoBar, "success", lambda *a, **k: gui_threads.append(QThread.currentThread())
    )
    window = Window()
    controller = updates.UpdateController(window)
    controller.check()
    assert entered.wait(1)
    assert controller._busy
    assert worker_threads != [threading.get_ident()]
    resume.set()
    deadline = time.monotonic() + 2
    while controller._busy and time.monotonic() < deadline:
        # Deliver this controller's queued signal without running other tests' pending widget callbacks.
        QCoreApplication.sendPostedEvents(controller, QEvent.Type.MetaCall)
        time.sleep(0.001)
    assert not controller._busy
    assert gui_threads == [qapp.thread()]
    controller.shutdown()
    delete_qobjects(controller, window)


def test_release_titles_and_bodies_remain_separate_blocks(qapp):
    releases = [
        updates.Release("v1.0.2", "First paragraph.\n\n- A change", "github", "", "", body_is_html=False),
        updates.Release(
            "v1.0.1", "<p>这是首次正式发布。</p><ul><li>新功能</li></ul>", "github", "", "", body_is_html=True
        ),
    ]
    window = Window()
    dialog = updates.ReleaseDialog(releases, False, window)
    try:
        blocks = []
        block = dialog.browser.document().begin()
        while block.isValid():
            blocks.append((block.text(), block.blockFormat().headingLevel()))
            block = block.next()
        assert ("v1.0.2", 2) in blocks
        assert ("v1.0.1", 2) in blocks
        assert ("First paragraph.", 0) in blocks
        assert ("这是首次正式发布。", 0) in blocks
        assert "A change" in dialog.browser.toPlainText()
        assert "新功能" in dialog.browser.toPlainText()
    finally:
        delete_qobjects(dialog, window)


def test_download_progress_and_result_stay_in_dialog(qapp, monkeypatch, tmp_path):
    translator = i18n.Translator("en_US")
    translator.load_dir(i18n.CORE_NAMESPACE, resource_path("i18n"))
    monkeypatch.setattr(i18n, "_translator", translator)
    monkeypatch.setattr(updates, "APP_VERSION", "1.0.1")
    monkeypatch.setattr(updates.InfoBar, "error", lambda *a, **k: None)
    monkeypatch.setattr(updates.InfoBar, "success", lambda *a, **k: None)
    monkeypatch.setattr(updates.QDesktopServices, "openUrl", lambda *a: True)
    window = Window()
    controller = updates.UpdateController(window)
    release = updates.Release("v1.0.2", "notes", "gitee", "https://gitee.com/a.zip", "a.zip")
    controller._checked([release], "")
    dialog = controller._dialog
    controller._downloading = True
    dialog.downloadButton.setEnabled(False)
    controller._progress(0, 0)
    assert dialog.progressBar.isVisible()
    assert dialog.progressBar.maximum() == 0
    controller._progress(1048576, 4194304)
    assert dialog.progressBar.value() == 25
    assert "1.0" in dialog.progressLabel.text()
    assert "4.0" in dialog.progressLabel.text()
    controller._checked([release], "")
    assert controller._dialog is dialog
    controller._downloaded(None, "offline")
    assert not dialog.progressBar.isVisible()
    assert dialog.downloadButton.isEnabled()
    controller._downloading = True
    controller._progress(4194304, 4194304)
    controller._downloaded(tmp_path / "a.zip", "")
    assert dialog.progressBar.value() == 100
    assert "a.zip" in dialog.progressLabel.text()
    controller.shutdown()
    delete_qobjects(controller, window)


def test_download_speed_uses_recent_bytes_and_drops_when_stalled(qapp, monkeypatch):
    window = Window()
    controller = updates.UpdateController(window)
    release = updates.Release("v1.0.2", "notes", "gitee", "https://gitee.com/a.zip", "a.zip")
    controller._dialog = updates.ReleaseDialog([release], True, window)
    controller._downloading = True
    now = [10.0]
    monkeypatch.setattr(updates.time, "monotonic", lambda: now[0])
    controller._speed_samples.append((10.0, 0))
    now[0] = 11.0
    controller._progress(2097152, 8388608)
    assert "2.00 MiB/s" in controller._dialog.progressLabel.text()
    now[0] = 15.0
    controller._refresh_download_status()
    assert "0.0 KiB/s" in controller._dialog.progressLabel.text()
    controller.shutdown()
    delete_qobjects(controller, window)


@pytest.mark.parametrize("result", ["success", "failure", "cancelled"])
def test_download_logs_start_and_outcome(qapp, monkeypatch, tmp_path, caplog, result):
    import logging

    window = Window()
    controller = updates.UpdateController(window)
    release = updates.Release("v1.0.2", "notes", "gitee", "https://gitee.com/a.zip", "a.zip")
    destination = tmp_path / "a.zip"
    monkeypatch.setattr(updates.QFileDialog, "getSaveFileName", lambda *a: (str(destination), ""))

    def download(*args):
        if result == "failure":
            raise OSError("offline")
        if result == "cancelled":
            raise updates.DownloadCancelledError()
        return destination

    class Worker:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(updates, "download_release", download)
    monkeypatch.setattr(updates.threading, "Thread", Worker)
    controller.downloadFinished.disconnect(controller._downloaded)
    with caplog.at_level(logging.INFO, logger=updates.log.name):
        controller._download(release)
    assert "Update download started:" in caplog.text
    outcome = {"success": "completed", "failure": "failed", "cancelled": "cancelled"}[result]
    assert f"Update download {outcome}:" in caplog.text
    assert "version=v1.0.2 source=gitee" in caplog.text
    controller.shutdown()
    delete_qobjects(controller, window)


@pytest.mark.parametrize("escape", [False, True])
def test_closing_dialog_cancels_download_without_feedback(qapp, monkeypatch, escape):
    monkeypatch.setattr(updates, "APP_VERSION", "1.0.1")
    messages = []
    monkeypatch.setattr(updates.InfoBar, "error", lambda *a, **k: messages.append("error"))
    monkeypatch.setattr(updates.InfoBar, "success", lambda *a, **k: messages.append("success"))
    monkeypatch.setattr(updates.QDesktopServices, "openUrl", lambda *a: messages.append("open"))
    window = Window()
    controller = updates.UpdateController(window)
    release = updates.Release("v1.0.2", "notes", "gitee", "https://gitee.com/a.zip", "a.zip")
    controller._checked([release], "")
    controller._downloading = True
    cancellation = controller._cancellation = updates.DownloadCancellation()
    if escape:
        controller._dialog.reject()
    else:
        controller._dialog.close()
    with pytest.raises(updates.DownloadCancelledError):
        cancellation.check()
    controller._downloaded(None, "socket closed")
    assert not controller._downloading
    assert not messages
    controller.shutdown()
    delete_qobjects(controller, window)


def test_skip_version_persists_and_only_suppresses_automatic_checks(qapp, store, monkeypatch):
    from nightreign_overlay.core.app_config import AppConfig
    from nightreign_overlay.core.config import ConfigStore

    monkeypatch.setattr(updates, "APP_VERSION", "1.0.1")
    config = store.bind(AppConfig, "app")
    window = Window()
    controller = updates.UpdateController(window, config=config)
    release = updates.Release("v1.0.2", "notes", "github", "https://example.com/a.zip", "a.zip")
    controller._checked([release], "")
    dialog = controller._dialog
    dialog.skipButton.click()
    assert config.skipped_update_version.value == "v1.0.2"
    assert not dialog.isVisible()
    store.flush()
    reloaded = ConfigStore(store.path)
    assert reloaded.bind(AppConfig, "app").skipped_update_version.value == "v1.0.2"
    controller._checked([release], "")
    assert not dialog.isVisible()
    # A different source or a temporary older result cannot bypass the skip.
    controller._checked([updates.Release("1.0.2", "mirror", "gitee", "", "")], "")
    assert not dialog.isVisible()
    controller._manual = True
    controller._checked([release], "")
    assert controller._dialog.isVisible()
    controller._dialog.close()
    controller._history = True
    controller._checked([release], "")
    assert controller._dialog.isVisible()
    assert not hasattr(controller._dialog, "skipButton")
    controller._dialog.close()
    newer = updates.Release("v1.0.3", "new notes", "gitee", "", "a.zip")
    controller._checked([newer, release], "")
    assert controller._dialog.isVisible()
    assert "v1.0.3" in controller._dialog.browser.toPlainText()
    controller.shutdown()
    delete_qobjects(reloaded, controller, window)


def test_release_dialog_background_follows_fluent_theme():
    # Fluent's global stylesheet registry spans this test session. Switch real
    # themes in a clean process so other tests' native widgets cannot interfere.
    import os
    import subprocess
    import sys
    import textwrap

    code = textwrap.dedent("""\
        from PyQt6.QtWidgets import QApplication, QWidget
        from qfluentwidgets import Theme, setTheme
        from nightreign_overlay.ui.components.updates import ReleaseDialog, Release
        from tests.support.qt import delete_qobjects

        app = QApplication([])
        window = QWidget()
        setTheme(Theme.DARK)
        dialog = ReleaseDialog([Release("v1.0.2", "notes", "cnb", "", "")], True, window)
        dialog.show()
        app.processEvents()
        assert dialog.palette().window().color().lightness() < 80
        setTheme(Theme.LIGHT)
        app.processEvents()
        assert dialog.palette().window().color().lightness() > 220
        setTheme(Theme.DARK)
        app.processEvents()
        assert dialog.palette().window().color().lightness() < 80
        delete_qobjects(dialog, window)
    """)
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", code],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
