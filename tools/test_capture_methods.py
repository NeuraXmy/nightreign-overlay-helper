"""Validate Windows capture methods against a deterministic Qt test window.

Run on Windows from the repository root:

    .venv\\Scripts\\python.exe tools\\test_capture_methods.py --layout all

The tool is intentionally separate from pytest because it needs a real desktop,
DWM composition, a native Maa DLL, and the user's monitor/DPI configuration.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "src" / "nightreign_overlay" / "plugins" / "capture"
WINDOW_TITLE = "ELDEN RING NIGHTREIGN"
PATTERN_SIZE = (960, 540)
METHODS = (
    "mss",
    "auto",
    "foreground",
    "background",
    "gdi",
    "framepool",
    "dxgi_desktop_dup",
    "dxgi_desktop_dup_window",
    "printwindow",
    "screendc",
)


def pattern_image() -> QImage:
    image = QImage(*PATTERN_SIZE, QImage.Format.Format_RGB32)
    image.fill(QColor("#101820"))
    painter = QPainter(image)
    try:
        colors = ("#e63946", "#f1fa8c", "#2a9d8f", "#457b9d", "#9b5de5", "#f4a261")
        cell_w, cell_h = 120, 90
        for row in range(6):
            for column in range(8):
                painter.fillRect(
                    column * cell_w,
                    row * cell_h,
                    cell_w - 4,
                    cell_h - 4,
                    QColor(colors[(row * 8 + column) % len(colors)]),
                )
        painter.setPen(QColor("#ffffff"))
        painter.drawRect(1, 1, image.width() - 3, image.height() - 3)
        painter.drawLine(0, image.height() // 2, image.width(), image.height() // 2)
        painter.drawLine(image.width() // 2, 0, image.width() // 2, image.height())
    finally:
        painter.end()
    return image


class PatternWindow(QWidget):
    def __init__(self, image: QImage) -> None:
        super().__init__()
        self._image = image
        self.setWindowTitle(WINDOW_TITLE)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAutoFillBackground(False)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor("#101820"))
            painter.drawImage(self.rect(), self._image)
        finally:
            painter.end()


def wait_for_window(app: QApplication, seconds: float = 0.5) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def crop_global(image: QImage, rect: QRect) -> QImage | None:
    local = rect.translated(-image.offset()).intersected(image.rect())
    if local != QRect(0, 0, rect.width(), rect.height()):
        return None
    return image.copy(local)


def compare(actual: QImage | None, expected: QImage) -> tuple[float, float]:
    if actual is None or actual.size() != expected.size():
        return 1.0, 255.0
    mismatches = 0
    total_error = 0
    pixels = actual.width() * actual.height() * 3
    for y in range(actual.height()):
        for x in range(actual.width()):
            a = actual.pixelColor(x, y)
            e = expected.pixelColor(x, y)
            for av, ev in zip((a.red(), a.green(), a.blue()), (e.red(), e.green(), e.blue()), strict=True):
                error = abs(av - ev)
                total_error += error
                mismatches += error > 8
    return mismatches / pixels, total_error / pixels


def make_backend(mode: str, log: logging.Logger):
    from nightreign_overlay.plugins.capture import plugin as capture

    if mode == "mss":
        return capture._MssCapture()
    if mode == "auto":
        return capture._AutoCapture(PLUGIN_DIR, "", log)
    backend = capture._MaaCapture(PLUGIN_DIR, mode)
    connect_start = time.perf_counter()
    backend.connect()
    return backend, (time.perf_counter() - connect_start) * 1000


def test_mode(mode: str, expected: QImage, client_rect: QRect, iterations: int, log: logging.Logger) -> dict:
    connect_ms = None
    backend = None
    try:
        backend_result = make_backend(mode, log)
        if isinstance(backend_result, tuple):
            backend, connect_ms = backend_result
        else:
            backend = backend_result
        samples: list[float] = []
        actual = None
        for _ in range(iterations + 1):
            started = time.perf_counter()
            frame = backend.grab()
            samples.append((time.perf_counter() - started) * 1000)
            if frame is not None:
                actual = crop_global(frame, client_rect)
        mismatch, mae = compare(actual, expected)
        return {
            "status": "pass" if actual is not None and mismatch == 0 else "mismatch",
            "connect_ms": connect_ms,
            "capture_ms_median": statistics.median(samples[1:]),
            "capture_ms_min": min(samples[1:]),
            "capture_ms_max": max(samples[1:]),
            "mismatch_ratio": mismatch,
            "mean_absolute_error": mae,
            "size": [actual.width(), actual.height()] if actual is not None else None,
        }
    except Exception as error:
        return {"status": "error", "error": f"{type(error).__name__}: {error}"}
    finally:
        if backend is not None:
            backend.close()


def run_layout(app: QApplication, layout: str, image: QImage, iterations: int, log: logging.Logger) -> dict:
    window = PatternWindow(image)
    if layout == "fullscreen":
        window.showFullScreen()
    else:
        window.resize(*PATTERN_SIZE)
        window.show()
    window.activateWindow()
    window.raise_()
    wait_for_window(app)
    from nightreign_overlay.plugins.capture.win32 import client_geometry, find_window_by_title

    hwnd = find_window_by_title(WINDOW_TITLE)
    if hwnd is None:
        raise RuntimeError("test window was not found")
    x, y, width, height = client_geometry(hwnd)
    client_rect = QRect(x, y, width, height)
    expected = image.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio)
    results = {mode: test_mode(mode, expected, client_rect, iterations, log) for mode in METHODS}
    window.close()
    wait_for_window(app, 0.2)
    return {"layout": layout, "client_rect": [x, y, width, height], "methods": results}


def main() -> int:
    if sys.platform != "win32":
        print("This diagnostic requires Windows.", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", choices=("window", "fullscreen", "all"), default="all")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path(".tmp/capture-methods"))
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO)
    app = QApplication.instance() or QApplication([])
    image = pattern_image()
    layouts = ("window", "fullscreen") if args.layout == "all" else (args.layout,)
    log = logging.getLogger("capture-methods")
    reports = [run_layout(app, layout, image, args.iterations, log) for layout in layouts]
    report = {"window_title": WINDOW_TITLE, "pattern_size": list(PATTERN_SIZE), "layouts": reports}
    report_path = args.output / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for layout in reports:
        print(f"[{layout['layout']}] client={layout['client_rect']}")
        for method, result in layout["methods"].items():
            print(
                f"  {method:24} {result['status']:8} "
                f"median={result.get('capture_ms_median', float('nan')):8.2f} ms "
                f"mae={result.get('mean_absolute_error', float('nan')):6.2f}"
            )
    print(f"Report: {report_path.resolve()}")
    return 0 if all(r["status"] == "pass" for layout in reports for r in layout["methods"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
