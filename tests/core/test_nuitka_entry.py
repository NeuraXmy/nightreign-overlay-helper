"""The compiled entry must preserve executable semantics and offer an isolated smoke check."""

import sys
from types import SimpleNamespace

import pytest
from scripts import nuitka_entry


@pytest.mark.parametrize("arguments", [[], ["--minimized"]])
def test_normal_start_uses_executable_semantics(monkeypatch, arguments):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "argv", ["overlay.exe", *arguments])
    calls = []

    def run():
        calls.append((sys.frozen, sys.argv[1:]))
        return 7

    monkeypatch.setitem(sys.modules, "nightreign_overlay.__main__", SimpleNamespace(main=run))
    assert nuitka_entry.main() == 7
    assert calls == [(True, arguments)]


def test_resource_check_bypasses_normal_application_start(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "argv", ["overlay.exe", "--check-runtime-resources"])
    checks = []
    monkeypatch.setitem(
        sys.modules, "scripts.check_runtime_resources", SimpleNamespace(main=lambda: checks.append(True))
    )
    # Any accidental normal startup would fail instead of opening the UI or requesting elevation.
    monkeypatch.setitem(sys.modules, "nightreign_overlay.__main__", None)
    assert nuitka_entry.main() == 0
    assert checks == [True]
    assert sys.frozen is True
