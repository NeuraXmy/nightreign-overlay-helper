"""One-shot setup, method validation and supervised subprocess failure paths."""

import copy
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEventLoop, QObject, QProcess, QTimer
from PyQt6.QtWidgets import QWidget

from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.plugins.capture import detection
from nightreign_overlay.plugins.capture.config import CAPTURE_MODES, CaptureConfig


def valid_report():
    return {
        "version": 1,
        "renderer": "D3D12/flip-discard",
        "complete": True,
        "error": "",
        "results": [
            {
                "mode": mode,
                "valid": mode != "gdi",
                "error": "stale frame" if mode == "gdi" else "",
                "max_color_error": 0,
                "samples_ms": [1 if mode == "gdi" else 10 + index] * 6,
            }
            for index, mode in enumerate(detection.TEST_METHODS)
        ],
    }


def wait_until(qapp, predicate):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start()
    QTimer.singleShot(3000, loop.quit)
    if not predicate():
        loop.exec()
    timer.stop()
    assert predicate(), "capture setup subprocess did not finish"


@pytest.fixture
def setup(store, tmp_path, monkeypatch):
    owner = QObject()
    config = store.bind(CaptureConfig, "plugins.capture")
    paused = []
    (tmp_path / "native").mkdir()
    (tmp_path / "native" / "MaaWin32Screencap.dll").touch()
    controller = detection.CaptureSetupController(
        config, tmp_path, lambda key, **values: f"{key}:{values}", paused.append, owner
    )
    monkeypatch.setattr(detection, "sys", SimpleNamespace(platform="win32"))
    yield controller, paused
    controller.shutdown()


def fake_helper(controller, tmp_path, monkeypatch, *, data=None, delay=0, code=0, raw=None):
    script = tmp_path / "fake_probe.py"
    payload = json.dumps(data or valid_report()) if raw is None else raw
    script.write_text(
        "import pathlib, sys, time\n"
        f"time.sleep({delay})\n"
        "path=pathlib.Path(sys.argv[sys.argv.index('--report')+1])\n"
        f"path.write_text({payload!r}, encoding='utf-8')\n"
        f"sys.exit({code})\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(detection, "helper_path", lambda: Path(sys.executable))
    set_arguments = controller.process.setArguments
    monkeypatch.setattr(controller.process, "setArguments", lambda args: set_arguments([str(script), *args]))


def test_fastest_method_must_pass_both_patterns():
    # GDI claims to be fastest, but its stale-frame result is excluded.
    assert detection.select_fastest(valid_report()) == "framepool"


@pytest.mark.parametrize("error", [12, 13])
def test_dark_pattern_uses_stricter_color_tolerance(error):
    report = valid_report()
    report["results"][1]["max_color_error"] = error
    if error == 12:
        assert detection.select_fastest(report) == "framepool"
    else:
        with pytest.raises(ValueError):
            detection.select_fastest(report)


@pytest.mark.parametrize(
    "bad", ["partial", "duplicate", "unknown", "missing", "nan", "short", "white", "all_failed"]
)
def test_invalid_or_incomplete_benchmarks_are_rejected(bad):
    report = valid_report()
    result = report["results"][1]
    if bad == "partial":
        report["complete"] = False
    elif bad == "duplicate":
        result["mode"] = "gdi"
    elif bad == "unknown":
        result["mode"] = "auto"
    elif bad == "missing":
        report["results"].pop()
    elif bad == "nan":
        result["samples_ms"][0] = float("nan")
    elif bad == "short":
        result["samples_ms"] = [1, 1, 1]
    elif bad == "white":
        result["max_color_error"] = 200
    else:
        for result in report["results"]:
            result["valid"] = False
    with pytest.raises(ValueError):
        detection.select_fastest(report)


@pytest.mark.parametrize("legacy", ["auto", "foreground", "background"])
def test_legacy_modes_migrate_to_mss(store, legacy):
    config = store.bind(CaptureConfig, "plugins.capture")
    assert config.mode.value == "mss"
    assert all(mode not in CAPTURE_MODES for mode in ("auto", "foreground", "background"))
    config.mode.set(legacy)
    assert config.mode.value == "mss"
    config.mode.set("gdi")
    assert config.mode.value == "gdi"


def test_success_saves_fixed_method_and_retains_report(qapp, setup, tmp_path, monkeypatch, store, caplog):
    controller, paused = setup
    fake_helper(controller, tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO):
        controller.start((-1920, 0, 1920, 1080))
        wait_until(qapp, lambda: not controller.active)
        controller._progress()
    logged = [
        message.split(": ", 1)[1]
        for message in caplog.messages
        if message.startswith("Capture benchmark result:")
    ]
    assert [json.loads(entry) for entry in logged] == valid_report()["results"]
    assert controller.config.mode.value == "framepool"
    assert controller.config.detection_prompted.value
    assert paused == [True, False]
    assert controller.report_path.is_file()
    store.flush()
    reopened = ConfigStore(tmp_path / "settings.yaml")
    assert reopened.bind(CaptureConfig, "plugins.capture").mode.value == "framepool"
    reopened.deleteLater()


@pytest.mark.parametrize(
    "failure", ["missing_component", "failed_to_start", "crash", "invalid_json", "all_failed", "timeout"]
)
def test_any_detection_failure_falls_back_to_mss(qapp, setup, tmp_path, monkeypatch, failure):
    controller, paused = setup
    controller.config.mode.set("gdi")
    if failure == "missing_component":
        monkeypatch.setattr(detection, "helper_path", lambda: tmp_path / "missing.exe")
    elif failure == "failed_to_start":
        bad_executable = tmp_path / "not-executable.exe"
        bad_executable.write_bytes(b"not a program")
        monkeypatch.setattr(detection, "helper_path", lambda: bad_executable)
    elif failure == "invalid_json":
        fake_helper(controller, tmp_path, monkeypatch, raw="{broken")
    elif failure == "all_failed":
        report = copy.deepcopy(valid_report())
        for result in report["results"]:
            result["valid"] = False
        fake_helper(controller, tmp_path, monkeypatch, data=report)
    else:
        fake_helper(
            controller,
            tmp_path,
            monkeypatch,
            code=17 if failure == "crash" else 0,
            delay=30 if failure == "timeout" else 0,
        )
    controller.start((0, 0, 1280, 720))
    if failure == "timeout":
        controller.timeout.start(30)
    wait_until(
        qapp, lambda: not controller.active and controller.process.state() == QProcess.ProcessState.NotRunning
    )
    assert controller.config.mode.value == "mss"
    assert "detection.failed" in controller.status
    assert not controller.poll.isActive() and not controller.timeout.isActive()
    assert paused[-1] is False


def test_cancel_kills_helper_and_retains_previous_method(qapp, setup, tmp_path, monkeypatch):
    controller, paused = setup
    controller.config.mode.set("dxgi_desktop_dup")
    fake_helper(controller, tmp_path, monkeypatch, delay=30)
    controller.start((0, 0, 1280, 720))
    wait_until(qapp, lambda: controller.process.state() == QProcess.ProcessState.Running)
    controller.cancel()
    wait_until(qapp, lambda: controller.process.state() == QProcess.ProcessState.NotRunning)
    assert controller.config.mode.value == "dxgi_desktop_dup"
    assert paused == [True, False]


def test_declining_initial_prompt_is_remembered(setup, monkeypatch):
    controller, _paused = setup
    prompts = []
    parent = QWidget()
    monkeypatch.setattr(detection, "display_geometries", lambda: [("primary", (0, 0, 1920, 1080))])

    class Dialog:
        def __init__(self, *_args):
            prompts.append(True)

        def exec(self):
            return 0

    monkeypatch.setattr(detection, "_CaptureSetupDialog", Dialog)
    controller.prompt_initial_setup(parent)
    controller.prompt_initial_setup(parent)
    assert prompts == [True]
    assert controller.config.mode.value == "mss"
    assert not controller.active
    parent.deleteLater()


def test_saved_setup_does_not_repeat_benchmark_at_startup(setup, monkeypatch):
    controller, paused = setup
    controller.config.mode.set("gdi")
    controller.config.detection_prompted.set(True)
    monkeypatch.setattr(
        detection, "_CaptureSetupDialog", lambda *_args: pytest.fail("setup must not prompt again")
    )
    parent = QWidget()
    controller.prompt_initial_setup(parent)
    assert not controller.active and paused == []
    assert controller.config.mode.value == "gdi"
    parent.deleteLater()


def test_manual_mode_change_cancels_detection(qapp, setup, tmp_path, monkeypatch):
    controller, paused = setup
    fake_helper(controller, tmp_path, monkeypatch, delay=30)
    controller.start((0, 0, 1280, 720))
    wait_until(qapp, lambda: controller.process.state() == QProcess.ProcessState.Running)
    controller.config.mode.set("printwindow")
    wait_until(qapp, lambda: controller.process.state() == QProcess.ProcessState.NotRunning)
    assert controller.config.mode.value == "printwindow"
    assert not controller.active and paused == [True, False]


@pytest.mark.parametrize("accept", [True, False])
@pytest.mark.parametrize("initial", [True, False])
def test_initial_and_manual_setup_confirm_selected_display_before_starting(
    qapp, setup, tmp_path, monkeypatch, accept, initial
):
    controller, paused = setup
    displays = [("primary", (0, 0, 1920, 1080)), ("secondary", (-1280, 0, 1280, 720))]
    monkeypatch.setattr(detection, "display_geometries", lambda: displays)
    dialogs = []

    class Dialog:
        def __init__(self, tr, choices, parent):
            dialogs.append(choices)
            self.display = SimpleNamespace(currentData=lambda: choices[1][1])

        def exec(self):
            return accept

    monkeypatch.setattr(detection, "_CaptureSetupDialog", Dialog)
    fake_helper(controller, tmp_path, monkeypatch)
    parent = QWidget()
    button = controller.create_button(parent)
    if initial:
        controller.prompt_initial_setup(parent)
    else:
        button.click()
    assert dialogs == [displays]
    if accept:
        assert controller.active and not button.isEnabled()
        assert controller.process.arguments()[-8:] == [
            "--x",
            "-1280",
            "--y",
            "0",
            "--width",
            "1280",
            "--height",
            "720",
        ]
        wait_until(qapp, lambda: not controller.active)
        assert controller.config.mode.value == "framepool" and paused == [True, False]
        assert button.isEnabled()
    else:
        assert not controller.active and paused == []
    controller.shutdown()
    parent.deleteLater()
