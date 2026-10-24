from src.screencap.engine import ScreencapEngine
from src.screencap.errors import ScreencapError, ScreencapInitError, ScreencapRuntimeError
from src.screencap.types import EngineStatus, ScreencapMethod, ScreencapMode

__all__ = [
    "ScreencapEngine",
    "ScreencapMode",
    "ScreencapMethod",
    "EngineStatus",
    "ScreencapError",
    "ScreencapInitError",
    "ScreencapRuntimeError",
    "get_engine",
]

_engine: ScreencapEngine | None = None


def get_engine() -> ScreencapEngine:
    global _engine
    if _engine is None:
        _engine = ScreencapEngine()
    return _engine
