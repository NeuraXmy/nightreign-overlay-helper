"""The standalone diagnostic must exercise the queued production worker and retain failure reports."""

import json
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QImage
from tools import diagnose_capture as diagnostic


@pytest.mark.parametrize("fail", [False, True])
def test_diagnostic_records_all_windows_modes_and_backend_failures(qapp, tmp_path, monkeypatch, fail):
    calls = []

    class Backend:
        def __init__(self, *_args):
            calls.append("opened")

        def grab(self):
            if fail:
                raise RuntimeError("Synthetic backend unavailable")
            image = QImage(16, 12, QImage.Format.Format_RGB32)
            image.fill(0x123456)
            image.setOffset(QPoint(-20, -10))
            return image

        def connect(self):
            pass

        selected_method = "test"

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(diagnostic.capture, "_MaaCapture", Backend)
    monkeypatch.setattr(diagnostic.capture, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(
        diagnostic,
        "sys",
        SimpleNamespace(
            platform="win32",
            argv=["diagnose_capture.py", "--output", str(tmp_path), "--region", "-18", "-8", "4", "4"],
        ),
    )
    # argparse uses the real sys.argv.
    monkeypatch.setattr("sys.argv", diagnostic.sys.argv)
    exit_code = diagnostic.main()
    report = json.loads((tmp_path / "report.json").read_text())
    assert "mss_error" not in report
    from nightreign_overlay.plugins.capture.config import CAPTURE_MODES

    assert [entry["requested_mode"] for entry in report["captures"]] == list(CAPTURE_MODES)
    assert len(calls) == 2 * len(CAPTURE_MODES)
    assert calls.count("closed") == len(CAPTURE_MODES)
    assert exit_code == (1 if fail else 0)
    for entry in report["captures"]:
        if fail:
            assert entry["status"] == "failed_or_timed_out"
        else:
            assert entry["region"]["shape"] == [4, 4, 3]
            assert (tmp_path / f"{entry['requested_mode']}-region.png").exists()
