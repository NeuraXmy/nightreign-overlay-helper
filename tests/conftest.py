"""Shared fixtures. Tests run on Qt's offscreen platform and never touch the user's data directory."""

from __future__ import annotations

import contextlib
import io
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# qfluentwidgets prints an advertisement on import.
with contextlib.redirect_stdout(io.StringIO()):
    import qfluentwidgets  # noqa: F401

from PyQt6.QtWidgets import QApplication

from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.paths import user_data_dir


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("NROH_DATA_DIR", str(tmp_path / "data"))
    user_data_dir.cache_clear()
    try:
        yield
    finally:
        user_data_dir.cache_clear()


@pytest.fixture
def store(qapp: QApplication, tmp_path: Path) -> Iterator[ConfigStore]:
    config_store = ConfigStore(tmp_path / "settings.yaml")
    yield config_store
    config_store.deleteLater()
