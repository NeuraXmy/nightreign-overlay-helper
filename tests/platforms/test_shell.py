"""Windows shell identity must be established before Qt initializes native windows."""

import ctypes
from unittest.mock import Mock

import pytest
from PIL import Image

from nightreign_overlay.core.paths import resource_path
from nightreign_overlay.meta import WINDOWS_APP_USER_MODEL_ID
from nightreign_overlay.platforms import shell


def test_non_windows_never_loads_shell32(monkeypatch):
    loader = Mock()
    monkeypatch.setattr(shell.sys, "platform", "darwin")
    monkeypatch.setattr(ctypes, "WinDLL", loader, raising=False)
    shell.configure_taskbar_identity()
    loader.assert_not_called()


@pytest.mark.parametrize("result", [0, -2147467259])
def test_windows_sets_explicit_identity_and_reports_failed_hresult(monkeypatch, caplog, result):
    api = Mock()
    api.SetCurrentProcessExplicitAppUserModelID.return_value = result
    monkeypatch.setattr(shell.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=api), raising=False)
    shell.configure_taskbar_identity()
    api.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(WINDOWS_APP_USER_MODEL_ID)
    assert ("HRESULT 0x80004005" in caplog.text) == (result < 0)


def test_shell_failure_does_not_prevent_launch(monkeypatch, caplog):
    monkeypatch.setattr(shell.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", Mock(side_effect=OSError("unavailable")), raising=False)
    shell.configure_taskbar_identity()
    assert "Could not configure Windows taskbar identity" in caplog.text


def test_bootstrap_sets_shell_identity_before_constructing_qapplication(monkeypatch):
    from nightreign_overlay import app

    calls = []
    monkeypatch.setattr(app, "setup_logging", Mock())
    monkeypatch.setattr(app, "configure_taskbar_identity", lambda: calls.append("shell"))

    class StopBeforeQtError(Exception):
        pass

    def create_qt(arguments):
        calls.append("qt")
        raise StopBeforeQtError

    monkeypatch.setattr(app, "QApplication", create_qt)
    with pytest.raises(StopBeforeQtError):
        app.run(["helper.exe"])
    assert calls == ["shell", "qt"]


def test_icon_has_native_taskbar_and_high_dpi_sizes(qapp):
    from nightreign_overlay.ui.theme import app_icon

    sizes = {16, 20, 24, 32, 40, 48, 64, 128, 256}
    with Image.open(resource_path("icons", "app.ico")) as image:
        assert {(size, size) for size in sizes} <= image.ico.sizes()
    icon = app_icon()
    for size in sizes:
        assert not icon.pixmap(size, size).isNull()
