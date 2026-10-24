"""Capture all deployment modes, recording monitor geometry and optional on-screen colour probes.

Run from the repository root using the application's Python environment. Requires a real desktop;
the report distinguishes captured pixels from unavailable backends instead of silently falling back.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtCore import QEventLoop, QObject, QRect, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication, QWidget

from nightreign_overlay.core.screens import screen_mappings
from nightreign_overlay.plugins.capture import plugin as capture
from nightreign_overlay.plugins.capture.api import FrameCaptured, crop_rgb
from nightreign_overlay.plugins.capture.config import CAPTURE_MODES


class Requests(QObject):
    grab = pyqtSignal(int, int, str, str, bool)


def capture_frame(mode: str, timeout_ms: int) -> tuple[FrameCaptured | None, bool]:
    """Use the production capture worker and its queued request/result path."""
    requests = Requests()
    worker = capture._CaptureWorker(Path(capture.__file__).parent, logging.getLogger("capture-diagnostic"))
    thread = QThread()
    worker.moveToThread(thread)
    requests.grab.connect(worker.grab, Qt.ConnectionType.QueuedConnection)
    thread.finished.connect(worker.close, Qt.ConnectionType.DirectConnection)
    thread.finished.connect(worker.deleteLater)
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    result = []

    def finished(_request, _generation, frame):
        result.append(frame)
        loop.quit()

    worker.grabbed.connect(finished, Qt.ConnectionType.QueuedConnection)
    thread.start()
    requests.grab.emit(1, 0, mode, "", False)
    timer.start(timeout_ms)
    loop.exec()
    timer.stop()
    thread.quit()
    # A hung native capture must not cause QThread destruction while still running.
    if not thread.wait(3000):
        capture._abandoned.append((thread, worker))
        return None, False
    return result[0] if result else None, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", *CAPTURE_MODES), default="all")
    parser.add_argument("--output", type=Path, default=Path(".tmp/capture-diagnostic"))
    parser.add_argument(
        "--markers",
        action="store_true",
        help="Briefly show colour probes on every screen (desktop capture only)",
    )
    parser.add_argument(
        "--region",
        type=int,
        nargs=4,
        metavar=("X", "Y", "W", "H"),
        help="Also crop this calibrated capture-pixel rectangle",
    )
    parser.add_argument("--timeout-ms", type=int, default=15000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(args.output / "capture.log", encoding="utf-8"),
        ],
    )
    app = QApplication.instance()
    if app is None:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        app = QApplication([])
    displays = app.screens()
    mappings = screen_mappings(displays)
    report = {"platform": sys.platform, "qt_platform": app.platformName(), "screens": [], "captures": []}
    markers = []
    probes = []
    for index, (screen, mapping) in enumerate(zip(displays, mappings, strict=True)):
        report["screens"].append(
            {
                "index": index,
                "name": screen.name(),
                "logical_geometry": screen.geometry().getRect(),
                "dpr": screen.devicePixelRatio(),
                "logical_dpi": screen.logicalDotsPerInch(),
                "capture_geometry": mapping.pixels.getRect(),
            }
        )
        if args.markers:
            color = (37 + index * 53 % 180, 190 - index * 31 % 140, 67 + index * 47 % 150)
            marker = QWidget(
                None,
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool,
            )
            marker.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            marker.setScreen(screen)
            center = mapping.logical.center()
            marker.setGeometry(center.x() - 24, center.y() - 24, 48, 48)
            marker.setStyleSheet(f"background-color: rgb{color};")
            marker.show()
            markers.append(marker)
            local = QRect(center.x() - mapping.logical.x() - 8, center.y() - mapping.logical.y() - 8, 16, 16)
            probes.append((mapping.to_pixels(local), color))
    if markers:
        loop = QEventLoop()
        QTimer.singleShot(800, loop.quit)
        loop.exec()

    modes = CAPTURE_MODES if args.mode == "all" else (args.mode,)
    complete = bool(displays)
    try:
        for mode in modes:
            backend = "maa-win32" if sys.platform == "win32" else "unsupported"
            entry = {"requested_mode": mode, "backend": backend}
            report["captures"].append(entry)
            frame, stopped = capture_frame(mode, args.timeout_ms)
            if frame is None:
                entry["status"] = "failed_or_timed_out"
                complete = False
            else:
                image = frame.image
                entry.update(
                    status="captured",
                    size=[image.width(), image.height()],
                    origin=[image.offset().x(), image.offset().y()],
                )
                entry["saved"] = image.save(str(args.output / f"{mode}.png"))
                complete &= entry["saved"]
                if args.region:
                    rect = QRect(*args.region)
                    crop = crop_rgb(image, rect)
                    entry["region"] = {
                        "requested": args.region,
                        "shape": list(crop.shape) if crop is not None else None,
                    }
                    complete &= crop is not None and crop.shape[:2] == (rect.height(), rect.width())
                    local = rect.translated(-image.offset()).intersected(image.rect())
                    if not local.isEmpty():
                        image.copy(local).save(str(args.output / f"{mode}-region.png"))
                if probes:
                    entry["probe_note"] = (
                        "Client-area capture may exclude probe windows; "
                        "inspect the game image and --region crop instead."
                    )
            if not stopped:
                entry["worker_stopped"] = False
                break
    finally:
        for marker in markers:
            marker.close()
        report["success"] = bool(complete)
        report_file = args.output / "report.json"
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {report_file.resolve()}")
        for entry in report["captures"]:
            print(entry["requested_mode"], entry["status"], entry.get("size"), entry.get("origin"))
    if capture._abandoned:
        # End only this standalone diagnostic process, without destructing a running native worker.
        print("Native capture did not stop. Report saved; exiting diagnostic process.", flush=True)
        logging.shutdown()
        os._exit(2)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
