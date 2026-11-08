"""User-initiated D3D12 benchmark, supervised out of process with an mss failure default."""

from __future__ import annotations

import ctypes
import json
import math
import statistics
import sys
from collections.abc import Callable
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    InfoBar,
    MessageBoxBase,
    PushButton,
    SubtitleLabel,
)

from nightreign_overlay.core.log import get_logger
from nightreign_overlay.core.paths import user_data_dir
from nightreign_overlay.plugins.capture.api import CaptureSetupApi
from nightreign_overlay.plugins.capture.config import CAPTURE_MODES, CaptureConfig

log = get_logger(__name__)
TEST_METHODS = tuple(mode for mode in CAPTURE_MODES if mode != "mss")
HELPER_FILENAME = "NightreignCaptureProbe.exe"
TIMEOUT_MS = 90_000


def helper_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "bin" / HELPER_FILENAME
    return Path(__file__).resolve().parents[4] / "bin" / HELPER_FILENAME


def select_fastest(report: object) -> str:
    """Accept only a complete, well-formed two-phase benchmark; never rank failed samples."""
    if not isinstance(report, dict) or report.get("version") != 1:
        raise ValueError("Invalid capture benchmark format")
    if report.get("complete") is not True or report.get("renderer") != "D3D12/flip-discard":
        raise ValueError("Incomplete DirectX benchmark")
    if report.get("error"):
        raise ValueError(str(report["error"]))
    results = report.get("results")
    if not isinstance(results, list) or len(results) != len(TEST_METHODS):
        raise ValueError("Missing capture method results")
    seen = set()
    candidates = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Invalid capture method result")
        mode = result.get("mode")
        if not isinstance(mode, str) or mode not in TEST_METHODS or mode in seen:
            raise ValueError("Unknown or duplicate capture method")
        seen.add(mode)
        if result.get("valid") is not True:
            continue
        samples = result.get("samples_ms")
        error = result.get("max_color_error")
        if (
            result.get("error")
            or not isinstance(error, int | float)
            or isinstance(error, bool)
            or not math.isfinite(error)
            or not 0 <= error <= 12
            or not isinstance(samples, list)
            or len(samples) != 6
            or any(
                not isinstance(sample, int | float)
                or isinstance(sample, bool)
                or not math.isfinite(sample)
                or sample <= 0
                for sample in samples
            )
        ):
            raise ValueError("Invalid capture validation or timing samples")
        candidates.append((statistics.median(samples), mode))
    if not candidates:
        raise ValueError("No capture method passed both color patterns")
    return min(candidates)[1]


def display_geometries() -> list[tuple[str, tuple[int, int, int, int]]]:
    """Physical monitor rectangles, including negative origins and mixed DPI layouts."""
    if sys.platform != "win32":
        return []

    class MonitorInfo(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("monitor", wintypes.RECT),
            ("work", wintypes.RECT),
            ("flags", wintypes.DWORD),
            ("device", wintypes.WCHAR * 32),
        ]

    api = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HANDLE, wintypes.HDC, ctypes.c_void_p, wintypes.LPARAM
    )
    api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    api.GetMonitorInfoW.restype = wintypes.BOOL
    api.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, callback_type, wintypes.LPARAM]
    api.EnumDisplayMonitors.restype = wintypes.BOOL
    monitors = []

    @callback_type
    def visit(monitor, _dc, _rect, _data):
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if api.GetMonitorInfoW(monitor, ctypes.byref(info)):
            rect = info.monitor
            monitors.append(
                (
                    not bool(info.flags & 1),
                    info.device,
                    (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
                )
            )
        return True

    change_dpi = api.SetThreadDpiAwarenessContext
    change_dpi.argtypes = [ctypes.c_void_p]
    change_dpi.restype = ctypes.c_void_p
    previous_dpi = change_dpi(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    if not previous_dpi:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not api.EnumDisplayMonitors(None, None, visit, 0):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        change_dpi(previous_dpi)
    return [(name, rect) for _secondary, name, rect in sorted(monitors)]


class CaptureSetupController(QObject, CaptureSetupApi):
    changed = pyqtSignal()

    def __init__(self, config: CaptureConfig, root: Path, tr: Callable, pause: Callable, parent: QObject):
        super().__init__(parent)
        self.config, self.root, self.tr, self._pause = config, root, tr, pause
        self.status = tr("detection.ready")
        self._logged_modes: set[str] = set()
        self.active = False
        self._window: QWidget | None = None
        self.report_path: Path | None = None
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self._fail("timeout"))
        self.poll = QTimer(self)
        self.poll.setInterval(300)
        self.poll.timeout.connect(self._progress)
        self.config.mode.valueChanged.connect(lambda _mode: self.cancel() if self.active else None)

    def create_button(self, parent: QWidget) -> PushButton:
        button = PushButton(self.tr("detection.start"), parent)
        button.setObjectName("captureDetectionButton")
        button.clicked.connect(lambda: self.prompt_setup(button.window()))

        def refresh() -> None:
            button.setEnabled(not self.active and sys.platform == "win32")
            button.setText(self.tr("detection.testing" if self.active else "detection.start"))

        self.changed.connect(refresh)
        refresh()
        return button

    def prompt_setup(self, parent: QWidget) -> None:
        if self.active:
            return
        self._window = parent
        try:
            displays = display_geometries()
            if not displays:
                raise RuntimeError("No display available")
        except Exception:
            log.exception("Cannot initialize capture test display")
            self._fail("display")
            return
        dialog = _CaptureSetupDialog(self.tr, displays, parent)
        if dialog.exec():
            self.start(dialog.display.currentData())

    def prompt_initial_setup(self, parent: QWidget) -> None:
        if sys.platform != "win32" or self.config.detection_prompted.value:
            return
        self.config.detection_prompted.set(True)
        self.prompt_setup(parent)

    def start(self, geometry: tuple[int, int, int, int]) -> None:
        if self.active or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        self.config.detection_prompted.set(True)
        self._logged_modes.clear()
        self.report_path = None
        if sys.platform != "win32":
            self._fail("platform")
            return
        executable = helper_path()
        dll = self.root / "native" / "MaaWin32Screencap.dll"
        if not executable.is_file() or not dll.is_file():
            self._fail("component")
            return
        try:
            directory = (
                user_data_dir() / "capture-tests" / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
            )
            directory.mkdir(parents=True)
            self.report_path = directory / "report.json"
            self.process.setStandardOutputFile(str(directory / "native.log"))
            self.process.setProgram(str(executable))
            arguments = ["--dll", str(dll.resolve()), "--report", str(self.report_path.resolve())]
            for key, value in zip(("x", "y", "width", "height"), geometry, strict=True):
                arguments.extend((f"--{key}", str(value)))
            self.process.setArguments(arguments)
            self._pause(True)
            self.active = True
            self.status = self.tr("detection.running")
            log.info("Starting D3D12 capture benchmark: geometry=%s report=%s", geometry, self.report_path)
            self.timeout.start(TIMEOUT_MS)
            self.poll.start()
            self.changed.emit()
            self.process.start()
        except Exception:
            log.exception("Cannot start capture benchmark")
            self._fail("start")

    def _progress(self) -> None:
        if self.report_path is None or not self.report_path.is_file():
            return
        try:
            report = json.loads(self.report_path.read_text(encoding="utf-8"))
            entries = report.get("results", [])
            if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
                return
            for entry in entries:
                mode = entry.get("mode")
                if isinstance(mode, str) and mode not in self._logged_modes:
                    log.info("Capture benchmark result: %s", json.dumps(entry, ensure_ascii=False))
                    self._logged_modes.add(mode)
        except (OSError, ValueError, AttributeError):
            pass  # A transient file read must not invalidate a running benchmark.

    def _process_error(self, error: QProcess.ProcessError) -> None:
        if self.active:
            log.warning("Capture benchmark process error: %s (%s)", error, self.process.errorString())
            self._fail("start" if error == QProcess.ProcessError.FailedToStart else "process")

    def _finished(self, code: int, status: QProcess.ExitStatus) -> None:
        if not self.active:
            return
        try:
            self._progress()
            if code != 0 or status != QProcess.ExitStatus.NormalExit or self.report_path is None:
                raise ValueError(f"Capture test exited with code {code}")
            report = json.loads(self.report_path.read_text(encoding="utf-8"))
            mode = select_fastest(report)
        except (OSError, ValueError, TypeError):
            log.exception("Capture benchmark failed")
            self._fail("validation")
            return
        self.active = False
        self.config.mode.set(mode)
        self.status = self.tr("detection.success")
        log.info("Capture benchmark selected fixed method: %s", mode)
        self._complete()

    def _fail(self, reason: str) -> None:
        log.warning("Capture setup failed (%s); falling back to mss", reason)
        self.active = False
        self.config.mode.set("mss")
        self.status = self.tr("detection.failed", reason=self.tr(f"detection.failure.{reason}"))
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        self._complete()

    def _complete(self) -> None:
        self.active = False
        self.timeout.stop()
        self.poll.stop()
        self._pause(False)
        self.changed.emit()
        if self._window is not None and self._window.isVisible():
            InfoBar.info(self.tr("detection.title"), self.status, duration=8000, parent=self._window)

    def cancel(self) -> None:
        if not self.active:
            return
        self.process.kill()
        self.status = self.tr("detection.cancelled")
        self._complete()

    def shutdown(self) -> None:
        self._window = None
        self.cancel()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)


class _CaptureSetupDialog(MessageBoxBase):
    """Keep display selection in the confirmation dialog rather than a separate page."""

    def __init__(self, tr: Callable, displays: list, parent: QWidget):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(tr("detection.title"), self.widget))
        description = BodyLabel(tr("detection.confirm"), self.widget)
        description.setWordWrap(True)
        self.viewLayout.addWidget(description)
        self.viewLayout.addWidget(BodyLabel(tr("detection.display"), self.widget))
        self.display = ComboBox(self.widget)
        for name, rect in displays:
            self.display.addItem(f"{name} · {rect[2]} × {rect[3]}", userData=rect)
        self.viewLayout.addWidget(self.display)
        self.yesButton.setText(tr("detection.start"))
        self.cancelButton.setText(tr("detection.cancel"))
        self.widget.setMinimumWidth(460)
