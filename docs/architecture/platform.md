# 平台抽象

## 职责

封装 Windows 与 macOS/Linux 的平台差异，使 core 和 plugins 可以统一调用。

## 关键文件

| 文件 | 职责 |
|------|------|
| [`src/nightreign_overlay/platforms/__init__.py`](../../src/nightreign_overlay/platforms/__init__.py) | `create_backend()` 工厂 |
| [`src/nightreign_overlay/platforms/base.py`](../../src/nightreign_overlay/platforms/base.py) | `PlatformBackend` 接口 |
| [`src/nightreign_overlay/platforms/windows.py`](../../src/nightreign_overlay/platforms/windows.py) | Windows ctypes 实现 |
| [`src/nightreign_overlay/platforms/generic.py`](../../src/nightreign_overlay/platforms/generic.py) | macOS/Linux 降级实现 |

## PlatformBackend 能力矩阵

| 能力 | Windows | macOS (generic) |
|------|---------|-----------------|
| 前台窗口标题 | `GetForegroundWindow + GetWindowTextW` | 不支持，视为始终前台 |
| 重申置顶 | `SetWindowPos(HWND_TOPMOST)` | 无操作 |
| 非激活点击 | 依赖 Qt flags | Cocoa `NSWindowStyleMaskNonactivatingPanel` |
| 管理员权限 | `IsUserAnAdmin` | 不适用 |
| 屏幕录制权限 | 无限制 | `CGPreflightScreenCaptureAccess` / `CGRequestScreenCaptureAccess` |
| `capture` 截图 | MaaWin32Screencap DLL | 不支持（请求失败并限频告警） |
| 透明悬浮窗 | 支持 | 默认不支持，可切普通窗口 |

## create_backend()

```python
def create_backend() -> PlatformBackend:
    if sys.platform == "win32":
        return WindowsBackend()
    return GenericBackend("macos" if sys.platform == "darwin" else "linux")
```

## WindowsBackend

- 使用 `ctypes.WinDLL("user32")` 和 `ctypes.WinDLL("shell32")`。
- 去除 pywin32 依赖。
- `ensure_topmost(window_id)`：每 1 秒由 `OverlayManager` 调用，防止全屏游戏抢占。

## GenericBackend

- `supports_transparent_overlay = False` 默认，因为 macOS 合成器可能把透明 Tool 窗口置于后台。
- `has_screen_capture_access()`：检测屏幕录制权限；缺失时 `region` 退化为半透明覆盖层。
- `capture` 插件在独立 QThread 中创建和使用 MaaWin32Screencap DLL；非 Windows 平台请求直接失败并限频告警。
- 多屏坐标转换统一使用 `core/screens.py`。macOS 屏幕原点按桌面最大 DPR 放置，每个屏幕保留自己的原生像素，避免混合缩放时坐标重叠。
- `configure_overlay_activation(window_id, non_activating)`：macOS 上设置 `NSWindowStyleMaskNonactivatingPanel`，防止点击透明悬浮窗激活整个应用。

## 必须保持的约束

- 调用方必须先检查 `supports_*` 属性，不能假设 Windows 行为。
- macOS 前台检测永远返回 true；任何依赖“仅游戏前台”的逻辑在 macOS 上都不会隐藏。
- 平台后端不持有 Qt 对象，只操作原生窗口句柄。

## 推荐做法：使用平台能力

```python
backend = ctx.services.get(PlatformBackend)
if backend is not None and backend.supports_foreground_detection:
    title = backend.foreground_window_title()
```

## 常见修改场景

| 场景 | 应修改位置 |
|------|-----------|
| 新增 Windows 原生能力 | `platforms/windows.py`；保持 ctypes，不引入 pywin32 |
| 新增 macOS 原生能力 | `platforms/generic.py`；注意 import Cocoa/objc 的条件 |
| 新增跨平台能力 | `platforms/base.py` 声明默认空实现；各后端可选覆盖 |
| 调整置顶频率 | `ui/overlay.py` `OverlayManager.TOPMOST_INTERVAL_MS` |

[返回架构索引](README.md)
