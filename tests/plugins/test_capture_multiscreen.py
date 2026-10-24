"""Exercise production capture/crop paths with synthetic desktops; no native capture permissions needed."""

import ctypes
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QColor, QImage

from nightreign_overlay.core import screens
from nightreign_overlay.plugins.capture import plugin as capture
from nightreign_overlay.plugins.capture import win32
from nightreign_overlay.plugins.capture.api import crop_rgb, make_frame
from nightreign_overlay.plugins.map_detect import overlay as map_overlay
from nightreign_overlay.plugins.region import plugin as region


def _screen(rect, ratio):
    return SimpleNamespace(geometry=lambda: rect, devicePixelRatio=lambda: ratio)


def _shot(image):
    return SimpleNamespace(
        width=image.width(),
        height=image.height(),
        bgra=bytes(image.constBits().asstring(image.sizeInBytes())),
    )


@pytest.mark.parametrize("mode", ["foreground", "background", "gdi"])
@pytest.mark.parametrize("ratio", [1, 1.25, 1.5, 1.75, 2])
@pytest.mark.parametrize("origin", [(-320, -180), (320, 180)])
def test_dll_window_pixels_map_to_global_calibration(tmp_path, monkeypatch, mode, ratio, origin):
    (tmp_path / "native").mkdir()
    (tmp_path / "native" / "MaaWin32Screencap.dll").touch()
    image = QImage(64, 48, QImage.Format.Format_RGB32)
    image.fill(0x12AB56)
    data = bytearray(_shot(image).bgra)
    data[3::4] = bytes(64 * 48)  # BGRX alpha is unspecified, including all-zero buffers.
    info = SimpleNamespace(data=bytes(data), width=64, height=48, step=64 * 4, channels=4)
    manager = SimpleNamespace(
        connect=lambda: True, selected_unit_name=lambda: mode, screencap=lambda: info, close=lambda: None
    )

    # A callable factory exposes the same method masks as the ctypes manager.
    def factory(*_args):
        return manager

    factory.METHOD_FOREGROUND = 40
    factory.METHOD_BACKGROUND = 18
    monkeypatch.setattr(win32, "Manager", factory)
    monkeypatch.setattr(win32, "find_window_by_title", lambda _title: 123)
    geometry = (*origin, round(64 * ratio), round(48 * ratio))
    monkeypatch.setattr(win32, "client_geometry", lambda hwnd: geometry)
    backend = capture._MaaCapture(tmp_path, mode)
    backend.connect()
    try:
        frame = make_frame(backend.grab())
        assert frame.image.size().width() == geometry[2]
        assert frame.image.offset() == QPoint(*origin)
        assert frame.image.pixelColor(0, 0).alpha() == 255
        crop = crop_rgb(frame.image, QRect(origin[0] + 8, origin[1] + 4, 16, 12))
        assert crop.shape == (12, 16, 3)
        assert (crop == [0x12, 0xAB, 0x56]).all()
        # Windows moved between captures: refresh origin without reconnecting.
        geometry = (origin[0] + 500, origin[1] - 200, *geometry[2:])
        assert backend.grab().offset() == QPoint(*geometry[:2])
        positions = iter([geometry, (0, 0, 64, 48)])
        monkeypatch.setattr(win32, "client_geometry", lambda _hwnd: next(positions))
        assert backend.grab() is None
    finally:
        backend.close()


@pytest.mark.parametrize("success", [True, False])
def test_win32_geometry_restores_thread_dpi_context(monkeypatch, success):
    contexts = []

    def set_context(context):
        contexts.append(context.value if hasattr(context, "value") else context)
        return 99

    def get_client(_hwnd, pointer):
        rect = ctypes.cast(pointer, ctypes.POINTER(win32.wintypes.RECT)).contents
        rect.right, rect.bottom = 1920, 1080
        return success

    def to_screen(_hwnd, pointer):
        point = ctypes.cast(pointer, ctypes.POINTER(win32.wintypes.POINT)).contents
        point.x, point.y = -1920, -1080
        return True

    api = SimpleNamespace(
        GetClientRect=get_client, ClientToScreen=to_screen, SetThreadDpiAwarenessContext=set_context
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: api, raising=False)
    if success:
        assert win32.client_geometry(123) == (-1920, -1080, 1920, 1080)
    else:
        with pytest.raises(OSError):
            win32.client_geometry(123)
    assert contexts[0] == ctypes.c_void_p(-4).value
    assert contexts[-1] == 99


def test_non_windows_auto_mode_uses_mss(monkeypatch):
    monkeypatch.setattr(capture, "sys", SimpleNamespace(platform="darwin"))
    worker = capture._CaptureWorker(Path(), SimpleNamespace(info=lambda *_args: None))
    image = QImage(2, 2, QImage.Format.Format_RGB32)
    image.fill(0x112233)
    monkeypatch.setattr(
        capture, "_MssCapture", lambda: SimpleNamespace(grab=lambda: image, close=lambda: None)
    )
    assert worker._grab("auto", "") is image
    worker.close()


@pytest.mark.parametrize("platform", ["win32", "darwin"])
@pytest.mark.parametrize("origin", [(-1920, 0), (2880, -1080)])
def test_selector_preview_and_map_overlay_use_the_capture_mapping(qapp, monkeypatch, platform, origin):
    monkeypatch.setattr(screens, "sys", SimpleNamespace(platform=platform))
    primary = _screen(QRect(0, 0, 1440, 900), 2)
    secondary = _screen(QRect(*origin, 1280, 720), 1.25)
    app = SimpleNamespace(
        screens=lambda: [primary, secondary], primaryScreen=lambda: primary, screenAt=lambda _pos: secondary
    )
    monkeypatch.setattr(region, "QGuiApplication", app)
    monkeypatch.setattr(region._SelectionDialog, "setScreen", lambda *_args: None)
    texts = region._SelectionTexts("Select", "Hint", "Cancel", "Save")
    dialog = region._SelectionDialog(texts, False, logging.getLogger("test"))
    local = QRect(20, 40, 160, 120)
    dialog.items = [region._ResizableRect(local, QColor("red"))]
    try:
        dialog._save()
        mapping = screens.screen_mappings([primary, secondary])[1]
        assert dialog.selected == mapping.to_pixels(local)
        expected = local.translated(secondary.geometry().topLeft())
        assert region._pixels_to_logical(dialog.selected) == expected
        positions, sizes = [], []
        overlay = SimpleNamespace(set_base_size=sizes.append, _move_to=positions.append)
        monkeypatch.setattr(map_overlay, "QGuiApplication", app)
        map_overlay.MapInfoOverlay.set_map_region(overlay, dialog.selected)
        assert positions == [expected.topLeft()]
        assert sizes == [expected.size()]
    finally:
        dialog.deleteLater()
