"""Windows taskbar identity, configured before Qt creates any native windows."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from nightreign_overlay.core.log import get_logger
from nightreign_overlay.meta import WINDOWS_APP_USER_MODEL_ID

log = get_logger(__name__)


def configure_taskbar_identity() -> None:
    """Keep the taskbar independent of the Python host's default shell identity."""
    if sys.platform != "win32":
        return
    try:
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        set_app_id = shell.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [wintypes.LPCWSTR]
        set_app_id.restype = ctypes.c_long  # HRESULT is a signed 32-bit LONG on Windows.
        result = set_app_id(WINDOWS_APP_USER_MODEL_ID)
        if result < 0:
            log.warning("Could not set Windows taskbar identity: HRESULT 0x%08X", result & 0xFFFFFFFF)
    except OSError:
        log.warning("Could not configure Windows taskbar identity", exc_info=True)
