# 基础插件层

> 基础插件 `kind=infrastructure`，默认启用，用户不能开关，为功能插件提供截图、热键、共享 HUD、区域标定能力。

---

## capture（截图引擎）

### 文件

- [`src/nightreign_overlay/plugins/capture/plugin.py`](../../src/nightreign_overlay/plugins/capture/plugin.py)
- [`src/nightreign_overlay/plugins/capture/api.py`](../../src/nightreign_overlay/plugins/capture/api.py)
- [`src/nightreign_overlay/plugins/capture/config.py`](../../src/nightreign_overlay/plugins/capture/config.py)
- [`src/nightreign_overlay/plugins/capture/win32.py`](../../src/nightreign_overlay/plugins/capture/win32.py)

### 职责

提供共享帧捕获，避免各检测插件各自截图。

### 截图方式

所有方式都由 MaaWin32Screencap DLL 实现（键值即方式位掩码，见 `win32.SCREENCAP_METHOD_MASKS`）；选定单一方式即固定该方式，不再自动测速。

| 方式 | 位掩码 | 说明 |
|------|------|------|
| `auto`（默认） | 全部位 | 测速选择最快方式 |
| `foreground` | `DXGI_DESKTOP_DUP_WINDOW \| SCREENDC` | 前台方式集合 |
| `background` | `FRAMEPOOL \| PRINTWINDOW` | 后台方式集合 |
| `gdi` … `screendc` | 单一方式位 | 手动固定 GDI / FramePool / DXGI 桌面复制 / DXGI 窗口复制 / PrintWindow / ScreenDC |

另可固定「截图进程」（默认按窗口标题自动检测游戏窗口）：PS5 串流等本机没有游戏窗口的场景，选择提供游戏画面的串流软件进程。

### API

```python
class CaptureApi:
    def latest_frame(self) -> FrameCaptured | None: ...
    def request_frame(self, callback: Callable[[FrameCaptured | None], None]) -> None: ...
    def acquire_stream(self, owner: str) -> None: ...
    def release_stream(self, owner: str) -> None: ...
    def hdr_enabled(self) -> bool: ...
    def game_client_rect(self) -> QRect | None: ...
```

### 数据流

```
功能插件 acquire_stream(owner)
        │
        ▼
CapturePlugin._timer 启动
        │
        ▼
_capture_stream_tick() → 发出 queued 请求（忙时丢弃该 tick）
        │
        ▼
_CaptureWorker._grab()（独立 QThread，Maa DLL）
        │
        ▼
make_frame(image, hdr=...) → queued 回传 GUI 线程 → 发布 FrameCaptured
        │
        ▼
各订阅者 _on_frame(frame)
```

### 辅助函数

- `crop_rgb(frame, region)`：裁剪为 `(h, w, 3)` uint8 RGB numpy 数组。
- `resize_to_height(image, height)`：保持宽高比缩放到指定高度。
- `hdr_to_sdr(image)`：gamma 色调映射。
- `normalize_image(image)`：LAB + CLAHE，用于地图检测 HDR。

### 必须保持的约束

- 首个 `acquire_stream` 启动定时截图；最后一个 `release_stream` 停止。
- `request_frame()` 提交与结果回传都检查 `ForegroundPolicy.detection_allowed`，回调始终在 GUI 线程执行。
- Maa 后端的创建、截图和关闭全部位于专用截图线程；GUI 线程只管理定时器和结果。
- 帧流最多保留一个在途请求；切换模式或截图进程以 generation 丢弃旧结果、释放旧后端并清空缓存。
- 截图仅在 Windows 上可用（DLL 是唯一后端）；其他平台请求以失败告警并按分钟限频重试。
- 屏幕原点按桌面最大 DPR 放置，屏内坐标按本屏 DPR 缩放；`core/screens.py` 统一标定、预览和地图/血条悬浮窗的转换。
- Windows DLL 图像使用当前客户区的物理桌面原点，抓取前后检查窗口位置/尺寸，变化时丢弃该帧并重试；DLL 尺寸与物理客户区不一致时按客户区尺寸归一化。
- Windows 客户区几何查询临时启用线程 per-monitor DPI awareness，并在结束时恢复原上下文。
- 多屏验证范围、实机诊断脚本及 macOS 副屏重新标定要求见 [多屏截图与 DPI](../guides/multiscreen-capture.md)。

### 推荐做法：消费截图

```python
def on_activate(self):
    capture = ctx.services.require(CaptureApi)
    ctx.subscribe(FrameCaptured, self._on_frame)
    capture.acquire_stream(self.id)
    ctx.on_cleanup(lambda: capture.release_stream(self.id))


def _on_frame(self, event: FrameCaptured):
    image = crop_rgb(event.image, region)
    ...
```

---

## input（全局热键）

### 文件

- [`src/nightreign_overlay/plugins/input/plugin.py`](../../src/nightreign_overlay/plugins/input/plugin.py)
- [`src/nightreign_overlay/plugins/input/api.py`](../../src/nightreign_overlay/plugins/input/api.py)
- [`src/nightreign_overlay/plugins/input/config.py`](../../src/nightreign_overlay/plugins/input/config.py)

### 职责

统一注册/监听全局热键，支持键盘、鼠标侧键、手柄。

### API

```python
class HotkeyApi:
    def register(self, action_id, default, callback) -> None: ...
    def unregister(self, action_id) -> None: ...
    def binding(self, action_id, default) -> HotkeyBinding: ...
    def set_binding(self, action_id, binding) -> None: ...
    def subscribe_capture(self, listener) -> None: ...
    def unsubscribe_capture(self, listener) -> None: ...
    def trigger_for_test(self, device, keys) -> None: ...
```

### 输入处理

- 键盘/鼠标：pynput。
- 手柄：pygame 每 100 ms 轮询；自动扫描连接；触发器/方向键抽象为按钮。
- 忽略鼠标左/右键；防止与正常游戏冲突。

### 匹配规则

后缀匹配：最近按下的 `len(binding.keys)` 个键按规范排序后等于绑定。

```python
def _matches_suffix(binding, pressed):
    return canonical(pressed[-len(binding) :]) == binding
```

### 必须保持的约束

- `HotkeyApi` 在 `on_load()` 注册，但物理监听在 `on_activate()` 启动。
- 录制快捷键时 `subscribe_capture` 隔离活动热键。
- macOS 记录 pynput 实际物理键，不跟随系统 Cmd/Ctrl 交换。
- 前台门控在 `_dispatch()` 中检查；快捷键只在 `input_allowed` 时触发。

---

## hud（共享悬浮窗）

### 文件

- [`src/nightreign_overlay/plugins/hud/plugin.py`](../../src/nightreign_overlay/plugins/hud/plugin.py)
- [`src/nightreign_overlay/plugins/hud/api.py`](../../src/nightreign_overlay/plugins/hud/api.py)
- [`src/nightreign_overlay/plugins/hud/overlay.py`](../../src/nightreign_overlay/plugins/hud/overlay.py)
- [`src/nightreign_overlay/plugins/hud/config.py`](../../src/nightreign_overlay/plugins/hud/config.py)

### 职责

提供共享 HUD 悬浮窗，多个功能插件向同一窗口贡献组件。

### API

```python
class HudApi:
    def add_widget(self, owner: str, widget: QWidget, order: int = 100) -> str: ...
    def remove_widget(self, token: str) -> None: ...
    def remove_owner(self, owner: str) -> None: ...
```

### HudOverlay

- 继承 `OverlayWindow`。
- 按 `order` 垂直排列组件。
- 组件显隐变化时自动重新布局。
- 组件可实现钩子：`set_hud_scale(scale)`、`set_hud_text_hidden(hidden)`。

### HudTimerBar

单条倒计时使用 400 px 基准进度条与阴影文字，并随 HUD 缩放。

### 必须保持的约束

- HUD 关闭时走隐藏流程，不把透明度设为零。
- 插件停用时必须移除自己的 HUD 组件。
- 无组件时 HUD 不显示。

---

## region（区域标定）

### 文件

- [`src/nightreign_overlay/plugins/region/plugin.py`](../../src/nightreign_overlay/plugins/region/plugin.py)
- [`src/nightreign_overlay/plugins/region/api.py`](../../src/nightreign_overlay/plugins/region/api.py)
- [`src/nightreign_overlay/plugins/region/config.py`](../../src/nightreign_overlay/plugins/region/config.py)

### 职责

提供统一的全屏选区对话框、区域持久化、预览窗口。

没有手动数据的区域通过 `CaptureApi.game_client_rect()` 按 16:9 默认 HUD 适配，有手动数据则优先使用。自动坐标不落盘，不增加自动/手动开关，也不拦截原有快捷键。支持范围和清除手动标定的操作见 [自动识别区域](automatic-regions.md)。

### API

```python
class RegionApi:
    def request_region(self, key, label=None, color=None, *, screenshot_path=None) -> QRect | None: ...
    def request_samples(self, targets: Sequence[RegionTarget]) -> dict[str, QImage] | None: ...
    def region(self, key: str) -> QRect | None: ...
    def region_source(self, key: str) -> str | None: ...
    def supports_automatic(self, key: str) -> bool: ...
    def clear_region(self, key: str) -> None: ...
    def show_preview(self, key: str, color: str | None = None) -> bool: ...
    def hide_preview(self) -> None: ...
    def save_region(self, key: str, rect: QRect) -> None: ...
```

### 坐标约定

- 保存：**设备像素**（`local * dpr + screen offset`）。
- 预览：通过 `_pixels_to_logical()` 转回 Qt 逻辑坐标。

### _SelectionDialog 交互

1. 主窗口隐藏，等待 250 ms，使窗口隐藏完成。
2. 冻结屏幕（有权限时）或半透明覆盖层（无权限时）。
3. 用户点击标注按钮 → 拖拽框选 → 调整角/边把手 → 保存/取消。
4. 主窗口恢复。

### RegionStatus

设置页状态部件：显示眼睛图标及手动/自动/等待状态；悬停时预览当前有效区域。支持自动适配的手动区域可单独清除；仅可见时定时刷新状态。

### 必须保持的约束

- 设置页可能在 `region` 激活前构造，`RegionStatus` 每次刷新/悬停都重新查找服务。
- 选区期间 `region_selection` UI 源保持前台门控开放。
- 标定矩形必须为正；保存时检查 width/height > 0。

---

## audio（音频服务）

隐藏基础插件 `audio` 提供 `AudioApi`，基于 QtMultimedia 复用一个延迟创建的播放器。功能插件持有自己的音频配置与调度，播放能力由服务统一提供；新播放替换正在播放的内容。文件缺失、解码失败或后端不可用记录日志，不中断计时。

“设置 → 通用”末尾的“主音量”范围为 0–100%，默认 100%。定长音频、循环音频及试听的实际音量均为各自音量乘以主音量；调整后立即作用于正在播放的音频。循环音频的淡入淡出同样乘以主音量，静音时保留播放和淡入淡出进度。

计时插件的配置、播报时机和清理规则见[计时功能](timers.md)。

## 常见修改场景

| 场景 | 应查看/修改 |
|------|------------|
| 新增截图模式/后端 | `plugins/capture/plugin.py` + `win32.py` |
| 新增输入设备支持 | `plugins/input/plugin.py` |
| 调整 HUD 布局/样式 | `plugins/hud/overlay.py` + `api.py` |
| 修改选区交互 | `plugins/region/plugin.py` `_SelectionDialog` |
| 新增区域预览行为 | `plugins/region/plugin.py` `_RegionPreview` |

[返回功能索引](README.md)
