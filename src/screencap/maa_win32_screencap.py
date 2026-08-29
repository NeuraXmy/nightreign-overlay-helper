"""
MaaWin32Screencap —— Python 绑定（ctypes，零编译依赖）

对应 MaaFramework 的 Python 绑定角色，封装两个外部扩展接口：
  1. CustomScreencapCallbacks —— 外部回调实现截图（对应 MaaCustomControllerCallbacks::screencap）
  2. Manager                    —— 内置 6 种 Win32 截图方式的测速选择 + 外部单元注册

用法：
    from maa_win32_screencap import Manager, ScreencapCallbacks, ImageBuffer

    # 方式一：外部回调实现截图
    def my_screencap(arg, out: ImageBuffer) -> int:
        # 把像素写入 out（BGRA/BGR），返回 1
        ...
    cb = ScreencapCallbacks(screencap=my_screencap, trans_arg=None)
    mgr = Manager(hwnd=None, methods=Manager.METHOD_NONE)
    mgr.register_custom_unit("my-unit", cb)
    mgr.connect()
    img = mgr.screencap()   # (width, height, channels, step, buffer)
    print(mgr.selected_unit_name())

    # 方式二：内置方式（需要窗口句柄）
    hwnd = find_window_by_title("记事本")  # 需自行用 ctypes 调 FindWindowW
    mgr = Manager(hwnd=hwnd, methods=Manager.METHOD_ALL)
    mgr.connect()
    img = mgr.screencap()

依赖：仅标准库 ctypes；可选 numpy（将 buffer 转为 numpy 数组）。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

__all__ = [
    "ImageBuffer",
    "ScreencapCallbacks",
    "Manager",
    "MaaWSBool",
    "dll_path",
    "set_dll_path",
]

# ---------------------------------------------------------------------------
# 加载动态库
# ---------------------------------------------------------------------------

_dll: Optional[ctypes.CDLL] = None
_dll_search_path: Optional[str] = None


def set_dll_path(path: str) -> None:
    """设置 MaaWin32Screencap.dll 所在目录（可选，便于从自定义路径加载）。"""
    global _dll_search_path, _dll
    _dll_search_path = path
    _dll = None  # 强制下次重新加载


def dll_path() -> Optional[str]:
    return _dll_search_path


def _default_search_paths():
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(here, "..", "build", "Release"),
        os.path.join(here, "..", "dist", "bin"),
        os.environ.get("MAA_WS_DLL_DIR", ""),
    ]


def _load_dll() -> ctypes.CDLL:
    global _dll
    if _dll is not None:
        return _dll

    import os

    candidates = []
    if _dll_search_path:
        candidates.append(os.path.join(_dll_search_path, "MaaWin32Screencap.dll"))
    for base in _default_search_paths():
        if base:
            candidates.append(os.path.join(base, "MaaWin32Screencap.dll"))

    errors = []
    for path in candidates:
        if os.path.exists(path):
            try:
                _dll = ctypes.CDLL(path)
                return _dll
            except OSError as e:  # pragma: no cover
                errors.append(f"{path}: {e}")
        else:
            errors.append(f"{path}: not found")

    # 兜底：依赖系统 PATH
    try:
        _dll = ctypes.CDLL("MaaWin32Screencap.dll")
        return _dll
    except OSError as e:  # pragma: no cover
        errors.append(f"system PATH: {e}")

    raise RuntimeError(
        "无法加载 MaaWin32Screencap.dll。请用 set_dll_path() 指定目录，"
        "或把 DLL 放入 PATH。错误详情:\n" + "\n".join(errors)
    )


# ---------------------------------------------------------------------------
# 数据类型（与 MaaWSCustomScreencap.h 对齐）
# ---------------------------------------------------------------------------

MaaWSBool = ctypes.c_ubyte


class ImageBuffer(ctypes.Structure):
    """MaaWSImageBuffer：像素（BGRA/BGR）+ 尺寸 + 步长。"""

    _fields_ = [
        ("data", ctypes.POINTER(ctypes.c_ubyte)),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("channels", ctypes.c_int32),
        ("step", ctypes.c_int32),
    ]

    def to_bytes(self) -> bytes:
        """复制像素数据为 bytes（按 step 行序）。"""
        if not self.data or self.width <= 0 or self.height <= 0:
            return b""
        row = self.step if self.step > 0 else self.width * self.channels
        return ctypes.string_at(self.data, row * self.height)

    def to_numpy(self):
        """转换为 numpy 数组（BnRGB/BGR）。需已安装 numpy。"""
        import numpy as np

        arr = np.frombuffer(self.to_bytes(), dtype=np.uint8)
        return arr.reshape(self.height, self.step, )[:, : self.width * self.channels].reshape(
            self.height, self.width, self.channels
        )

    @dataclass
    class Info:
        width: int
        height: int
        channels: int
        step: int
        data: bytes


# 回调原型。
# 注意：ctypes 回调收到 POINTER(Structure) 参数时转换成的 Structure 是【副本】，
# 对其字段的修改不会写回原生内存。因此 screencap 回调一律用裸指针 (c_void_p)，
# 由包装层通过 ImageBuffer.from_address 构造"指针背书"的结构，写入才能持久。
_screencap_cb_type = ctypes.CFUNCTYPE(MaaWSBool, ctypes.c_void_p, ctypes.c_void_p)
_bool_cb_type = ctypes.CFUNCTYPE(MaaWSBool, ctypes.c_void_p)


class ScreencapCallbacks:
    """
    C 回调封装（MaaWSCustomScreencapCallbacks）。
    screencap(arg, out) -> int：把图像写入 out（推荐 4 通道 BGRA），成功返回 1。
    connect/connected/inactive 可选，返回 1/0。
    """

    def __init__(
        self,
        screencap: Callable[[Optional[object], ImageBuffer], int],
        trans_arg: Optional[object] = None,
        connect: Optional[Callable[[Optional[object]], int]] = None,
        connected: Optional[Callable[[Optional[object]], int]] = None,
        inactive: Optional[Callable[[Optional[object]], int]] = None,
    ):
        self._trans_arg = trans_arg
        self._screencap_cb = self._make_screencap_wrapper(screencap) if screencap else None
        self._connect_cb = _bool_cb_type(connect) if connect else None
        self._connected_cb = _bool_cb_type(connected) if connected else None
        self._inactive_cb = _bool_cb_type(inactive) if inactive else None

    def _make_screencap_wrapper(self, user_fn):
        @_screencap_cb_type
        def wrapper(trans_arg, buf_ptr):
            if not buf_ptr:
                return 0
            try:
                out = ImageBuffer.from_address(buf_ptr)
            except (ValueError, TypeError):
                return 0
            return 1 if user_fn(trans_arg, out) else 0

        wrapper._user_fn = user_fn  # 保活引用（防 GC 释放用户函数）
        return wrapper

    @property
    def _as_param_(self):
        return 1  # 兼容旧接口占位；实际走 _ctor

    def _ctor(self) -> ctypes.Structure:
        class Struct(ctypes.Structure):
            _fields_ = [
                ("connect", _bool_cb_type),
                ("connected", _bool_cb_type),
                ("screencap", _screencap_cb_type),
                ("inactive", _bool_cb_type),
            ]

        s = Struct()
        s.connect = self._connect_cb or _bool_cb_type()
        s.connected = self._connected_cb or _bool_cb_type()
        s.screencap = self._screencap_cb
        s.inactive = self._inactive_cb or _bool_cb_type()
        return s


class Manager:
    """截图管理器（MaaWSManager*）。"""

    # 截图方式位掩码（与 C 头文件常数一致）
    METHOD_NONE = 0
    METHOD_GDI = 1 << 0
    METHOD_FRAMEPOOL = 1 << 1
    METHOD_DXGI_DESKTOP_DUP = 1 << 2
    METHOD_DXGI_DESKTOP_DUP_WINDOW = 1 << 3
    METHOD_PRINTWINDOW = 1 << 4
    METHOD_SCREENDC = 1 << 5
    METHOD_ALL = (1 << 64) - 1
    METHOD_FOREGROUND = METHOD_DXGI_DESKTOP_DUP_WINDOW | METHOD_SCREENDC
    METHOD_BACKGROUND = METHOD_FRAMEPOOL | METHOD_PRINTWINDOW

    def __init__(self, hwnd: Optional[int] = None, methods: int = METHOD_ALL):
        """
        hwnd: 目标窗口句柄（int，即 HWND）。为 None 时内置前台方式不可用。
        methods: 参与测速的内置方式位掩码。
        """
        dll = _load_dll()
        dll.MaaWSManagerCreate.restype = ctypes.c_void_p
        dll.MaaWSManagerCreate.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        dll.MaaWSManagerDestroy.restype = None
        dll.MaaWSManagerDestroy.argtypes = [ctypes.c_void_p]
        dll.MaaWSManagerRegisterCustomUnit.restype = MaaWSBool
        dll.MaaWSManagerRegisterCustomUnit.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        dll.MaaWSManagerConnect.restype = MaaWSBool
        dll.MaaWSManagerConnect.argtypes = [ctypes.c_void_p]
        dll.MaaWSManagerScreencap.restype = MaaWSBool
        dll.MaaWSManagerScreencap.argtypes = [ctypes.c_void_p, ctypes.POINTER(ImageBuffer)]
        dll.MaaWSManagerSelectedUnitName.restype = ctypes.c_char_p
        dll.MaaWSManagerSelectedUnitName.argtypes = [ctypes.c_void_p]
        dll.MaaWSManagerInactive.restype = None
        dll.MaaWSManagerInactive.argtypes = [ctypes.c_void_p]

        self._dll = dll
        self._handle = dll.MaaWSManagerCreate(hwnd or 0, methods)
        if not self._handle:
            raise RuntimeError("MaaWSManagerCreate failed")

        self._callbacks: list[ScreencapCallbacks] = []  # 持有回调对象引用，防 GC
        self._native_structs: list = []  # 持有回调结构体内存，C 侧保存了其指针

    def register_custom_unit(self, name: str, callbacks: ScreencapCallbacks) -> bool:
        """注册外部自定义截图单元（C 回调实现）。"""
        # 保活：C 侧 CustomScreencapBridge 会保存 callbacks 结构体指针，
        # 并在 connect()/screencap() 时调用其中的函数指针；若 Python 侧被 GC，
        # 结构体内存与回调对象释放后即为悬垂指针（访问违例）。
        self._callbacks.append(callbacks)
        c_struct = callbacks._ctor()
        self._native_structs.append(c_struct)
        return bool(
            self._dll.MaaWSManagerRegisterCustomUnit(
                self._handle, name.encode("utf-8"), ctypes.cast(ctypes.byref(c_struct), ctypes.c_void_p), ctypes.c_void_p(id(callbacks))
            )
        )

    def connect(self) -> bool:
        """连接 + 测速选择最快截图方式。"""
        return bool(self._dll.MaaWSManagerConnect(self._handle))

    def screencap(self) -> Optional[ImageBuffer.Info]:
        """截图一次。成功返回 (width, height, channels, step, data) 容器，失败返回 None。"""
        buf = ImageBuffer()
        if not self._dll.MaaWSManagerScreencap(self._handle, ctypes.byref(buf)):
            return None
        return ImageBuffer.Info(
            width=buf.width,
            height=buf.height,
            channels=buf.channels,
            step=buf.step,
            data=buf.to_bytes(),
        )

    def selected_unit_name(self) -> Optional[str]:
        name = self._dll.MaaWSManagerSelectedUnitName(self._handle)
        return name.decode("utf-8") if name else None

    def inactive(self) -> None:
        self._dll.MaaWSManagerInactive(self._handle)

    def __del__(self):
        if getattr(self, "_handle", None):
            try:
                self._dll.MaaWSManagerDestroy(self._handle)
            except Exception:
                pass
            self._handle = None


# ---------------------------------------------------------------------------
# 工具：按窗口标题找 HWND（Windows）
# ---------------------------------------------------------------------------

def find_window_by_title(title: str) -> Optional[int]:
    """按窗口标题查找顶层窗口句柄（不区分大小写，模糊匹配）。"""
    _user32 = ctypes.windll.user32

    results = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def enum_proc(hwnd, lparam):
        length = _user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            if title.lower() in buf.value.lower():
                results.append(hwnd)
        return True

    _user32.EnumWindows(enum_proc, 0)
    return results[0] if results else None


def foreground_window() -> Optional[int]:
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    return int(hwnd) if hwnd else None