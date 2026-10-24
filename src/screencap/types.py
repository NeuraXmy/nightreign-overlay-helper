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


class ScreencapMethod(Enum):
    """MaaWin32Screencap 具体截图方式的位掩码键值对（与 C 头文件常量一致）。

    选择单一方式时即固定使用该截图方式，不再参与自动测速选择。
    """

    GDI = 1 << 0
    FRAMEPOOL = 1 << 1
    DXGI_DESKTOP_DUP = 1 << 2
    DXGI_DESKTOP_DUP_WINDOW = 1 << 3
    PRINTWINDOW = 1 << 4
    SCREENDC = 1 << 5
