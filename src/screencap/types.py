from enum import Enum


class EngineStatus(Enum):
    UNINITIALIZED = 0
    INITIALIZING = 1
    CONNECTED = 2
    FAILED = 3
    SHUTDOWN = 4


class ScreencapMode(Enum):
    AUTO = 0
    FOREGROUND = 1
    BACKGROUND = 2
