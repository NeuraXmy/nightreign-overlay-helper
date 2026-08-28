import time

import cv2
import numpy as np
from PIL import Image

from src.common import GAME_WINDOW_TITLE
from src.logger import info, warning, error
from src.screencap.errors import ScreencapInitError, ScreencapRuntimeError
from src.screencap.hwnd_resolver import find_game_hwnd
from src.screencap.native_loader import get_native_dll_dir, get_native_dll_path
from src.screencap.types import EngineStatus, ScreencapMode


class ScreencapEngine:
    def __init__(self):
        self._status: EngineStatus = EngineStatus.UNINITIALIZED
        self._mgr = None
        self._selected_method_name: str | None = None
        self._last_frame: Image.Image | None = None
        self._last_frame_time: float = 0.0

    @property
    def status(self) -> EngineStatus:
        return self._status

    @property
    def selected_method_name(self) -> str | None:
        return self._selected_method_name

    def initialize(self, mode: ScreencapMode = ScreencapMode.AUTO) -> None:
        try:
            self._status = EngineStatus.INITIALIZING

            dll_path = get_native_dll_path()
            if not dll_path.exists():
                raise ScreencapInitError(
                    "dll_not_found",
                    f"MaaWin32Screencap.dll not found at {dll_path}",
                )

            from src.screencap.maa_win32_screencap import Manager, set_dll_path

            set_dll_path(str(get_native_dll_dir()))

            hwnd = find_game_hwnd(GAME_WINDOW_TITLE)
            if hwnd is None:
                raise ScreencapInitError(
                    "connect_failed",
                    f"Game window '{GAME_WINDOW_TITLE}' not found.",
                )

            if mode == ScreencapMode.FOREGROUND:
                methods = Manager.METHOD_FOREGROUND
            elif mode == ScreencapMode.BACKGROUND:
                methods = Manager.METHOD_BACKGROUND
            else:
                methods = Manager.METHOD_ALL

            self._mgr = Manager(hwnd=hwnd, methods=methods)

            if not self._mgr.connect():
                raise ScreencapInitError(
                    "connect_failed",
                    "Manager.connect() returned False.",
                )

            self._selected_method_name = self._mgr.selected_unit_name()
            info(f"ScreencapEngine initialized, selected method: {self._selected_method_name}")
            self._status = EngineStatus.CONNECTED

        except ScreencapInitError:
            self._status = EngineStatus.FAILED
            raise
        except Exception as e:
            self._status = EngineStatus.FAILED
            raise ScreencapInitError("connect_failed", str(e)) from e

    def grab_fullscreen(self) -> Image.Image:
        if self._status != EngineStatus.CONNECTED or self._mgr is None:
            raise ScreencapRuntimeError("not_connected", "Engine is not connected.")

        try:
            from src.config import Config
            cache_interval = Config.get().update_interval
        except Exception:
            cache_interval = 0.0

        now = time.time()
        if (
            self._last_frame is not None
            and cache_interval > 0
            and (now - self._last_frame_time) < cache_interval
        ):
            return self._last_frame

        info_obj = self._mgr.screencap()
        if info_obj is None:
            self._last_frame = None
            raise ScreencapRuntimeError("grab_failed", "mgr.screencap() returned None.")

        try:
            arr = np.frombuffer(info_obj.data, dtype=np.uint8)
            row_len = info_obj.step if info_obj.step > 0 else info_obj.width * info_obj.channels
            arr = arr.reshape(info_obj.height, row_len)[:, : info_obj.width * info_obj.channels]
            arr = arr.reshape(info_obj.height, info_obj.width, info_obj.channels)

            if info_obj.channels == 4:
                arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2RGB)
            elif info_obj.channels == 3:
                arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
            else:
                raise ScreencapRuntimeError(
                    "grab_failed",
                    f"Unsupported channel count: {info_obj.channels}",
                )

            img = Image.fromarray(arr)
            self._last_frame = img
            self._last_frame_time = now
            return img

        except ScreencapRuntimeError:
            self._last_frame = None
            raise
        except Exception as e:
            self._last_frame = None
            raise ScreencapRuntimeError("grab_failed", str(e)) from e

    def shutdown(self) -> None:
        if self._mgr is not None:
            try:
                self._mgr.inactive()
            except Exception as e:
                warning(f"ScreencapEngine.shutdown: inactive() failed: {e}")
            try:
                del self._mgr
            except Exception:
                pass
            self._mgr = None
        self._last_frame = None
        self._status = EngineStatus.SHUTDOWN
        info("ScreencapEngine shutdown.")
