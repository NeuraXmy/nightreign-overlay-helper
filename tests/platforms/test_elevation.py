"""Elevation handoff without launching an elevated process or displaying native dialogs."""

from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest

from nightreign_overlay.platforms import elevation


@pytest.fixture
def shell(monkeypatch):
    api = Mock()
    api.IsUserAnAdmin.return_value = False
    api.ShellExecuteW.return_value = 42
    monkeypatch.setattr(elevation.sys, "platform", "win32")
    monkeypatch.setattr(elevation, "_shell_api", lambda: api)
    monkeypatch.setattr(elevation, "_show_failure", Mock())
    return api


def test_non_windows_does_not_request_elevation(shell, monkeypatch):
    monkeypatch.setattr(elevation.sys, "platform", "darwin")
    assert elevation.ensure_administrator() is None
    shell.IsUserAnAdmin.assert_not_called()
    shell.ShellExecuteW.assert_not_called()


def test_already_admin_continues_without_relaunch(shell):
    shell.IsUserAnAdmin.return_value = True
    assert elevation.ensure_administrator() is None
    shell.ShellExecuteW.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        ["-X", "utf8", "main.py", "--data-dir", "C:\\data folder\\", "--debug"],
        ["-m", "nightreign_overlay", "--minimized"],
    ],
)
def test_source_handoff_preserves_python_options_arguments_and_cwd(shell, monkeypatch, arguments):
    monkeypatch.setattr(elevation.sys, "frozen", False, raising=False)
    monkeypatch.setattr(elevation.sys, "executable", "C:\\Python folder\\python.exe")
    monkeypatch.setattr(elevation.sys, "orig_argv", ["python", *arguments])
    monkeypatch.setattr(elevation.os, "getcwd", lambda: "C:\\project folder")
    assert elevation.ensure_administrator() == 0
    shell.ShellExecuteW.assert_called_once_with(
        None,
        "runas",
        "C:\\Python folder\\python.exe",
        subprocess.list2cmdline(arguments),
        "C:\\project folder",
        1,
    )
    elevation._show_failure.assert_not_called()


def test_frozen_handoff_uses_app_arguments(shell, monkeypatch):
    monkeypatch.setattr(elevation.sys, "frozen", True, raising=False)
    monkeypatch.setattr(elevation.sys, "argv", ["helper.exe", "--data-dir", "C:\\data folder"])
    assert elevation.ensure_administrator() == 0
    assert shell.ShellExecuteW.call_args.args[3] == '--data-dir "C:\\data folder"'


@pytest.mark.parametrize("error", [0, 5, 31, 32])
def test_refused_or_failed_elevation_exits_with_visible_error(shell, error):
    shell.ShellExecuteW.return_value = error
    assert elevation.ensure_administrator() == 1
    elevation._show_failure.assert_called_once()
    assert str(error) in elevation._show_failure.call_args.args[0]


def test_shell_exception_exits_with_visible_error(shell):
    shell.ShellExecuteW.side_effect = OSError("UAC unavailable")
    assert elevation.ensure_administrator() == 1
    elevation._show_failure.assert_called_once_with("UAC unavailable")


@pytest.mark.parametrize("exit_code", [0, 1])
def test_entrypoint_exits_before_application_bootstrap(monkeypatch, exit_code):
    from nightreign_overlay import __main__ as entrypoint

    monkeypatch.setattr(elevation, "ensure_administrator", lambda: exit_code)
    assert entrypoint.main() == exit_code
