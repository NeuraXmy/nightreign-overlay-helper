import time

import cv2
import numpy as np
from PIL import Image

from src.common import GAME_WINDOW_TITLE
from src.logger import info, warning, error
from src.screencap.errors import ScreencapInitError, ScreencapRuntimeError
from src.screencap.hwnd_resolver import find_game_hwnd
from src.screencap.native_loader import get_native_dll_dir, get_native_dll_path
from src.screencap.types import EngineStatus, ScreencapMethod, ScreencapMode


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

    @staticmethod
    def _methods_mask(mode: ScreencapMode | ScreencapMethod) -> int:
        """把模式/具体方式换算为 MaaWin32Screencap 的方式位掩码。

        具体方式 (ScreencapMethod) 的键值即位掩码，单一候选等于固定
        该截图方式，不再参与自动测速选择。
        """
        from src.screencap.maa_win32_screencap import Manager

        if isinstance(mode, ScreencapMethod):
            return mode.value
        if mode == ScreencapMode.FOREGROUND:
            return Manager.METHOD_FOREGROUND
        if mode == ScreencapMode.BACKGROUND:
            return Manager.METHOD_BACKGROUND
        return Manager.METHOD_ALL

    def initialize(
        self,
        mode: ScreencapMode | ScreencapMethod = ScreencapMode.AUTO,
        process: str = "",
    ) -> None:
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

            hwnd = find_game_hwnd(GAME_WINDOW_TITLE, process_name=process or None)
            if hwnd is None:
                target = process or f"window '{GAME_WINDOW_TITLE}'"
                raise ScreencapInitError(
                    "connect_failed",
                    f"Capture target {target} not found.",
                )

            methods = self._methods_mask(mode)

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
