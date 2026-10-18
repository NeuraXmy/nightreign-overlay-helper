# L2 · 核心底座

## 职责

提供与 UI 和插件无关的基础设施：配置持久化、类型化事件总线、服务注册表、国际化、前台窗口监控、路径/日志。

## 关键文件

| 文件 | 职责 |
|------|------|
| [`src/nightreign_overlay/core/config.py`](../src/nightreign_overlay/core/config.py) | 声明式配置、ConfigStore、原子写入 |
| [`src/nightreign_overlay/core/events.py`](../src/nightreign_overlay/core/events.py) | 类型化事件总线 |
| [`src/nightreign_overlay/core/services.py`](../src/nightreign_overlay/core/services.py) | 服务注册表 |
| [`src/nightreign_overlay/core/game_window.py`](../src/nightreign_overlay/core/game_window.py) | 前台窗口监控 + ForegroundPolicy |
| [`src/nightreign_overlay/core/i18n.py`](../src/nightreign_overlay/core/i18n.py) | YAML 国际化 |
| [`src/nightreign_overlay/core/paths.py`](../src/nightreign_overlay/core/paths.py) | 数据/日志/资源路径 |
| [`src/nightreign_overlay/core/log.py`](../src/nightreign_overlay/core/log.py) | 分模块日志 |
| [`src/nightreign_overlay/core/app_config.py`](../src/nightreign_overlay/core/app_config.py) | 应用级配置声明 |
| [`src/nightreign_overlay/core/input.py`](../src/nightreign_overlay/core/input.py) | 输入设备枚举、HotkeyBinding 类型 |
| [`src/nightreign_overlay/core/images.py`](../src/nightreign_overlay/core/images.py) | 支持 Unicode 路径的 OpenCV 图片读写 |

OpenCV 图片资源统一使用 `read_cv2_image(path, flags)`：通过 `Path.read_bytes()` 读取，再用
`cv2.imdecode()` 解码，避免 Windows 上 `cv2.imread()` 无法读取中文安装路径。默认返回 BGR，
`IMREAD_UNCHANGED` 保留透明通道；文件缺失抛 `FileNotFoundError`，解码失败抛包含资源路径的
`OSError`。调用方负责颜色转换及缺失资源的降级策略。

图片写入使用 `write_cv2_image(path, image, params)`：先 `cv2.imencode()` 编码，再通过
`Path.write_bytes()` 写入，避免 `cv2.imwrite()` 在中文用户数据目录下写入失败。输入沿用
OpenCV 的 BGR/BGRA 或灰度格式，编码失败抛包含目标路径的 `OSError`；文件系统错误原样传播。

---

## 2.1 配置系统

### 核心类

- `Option[T]`：默认值 + 校验器描述。
- `BoolOption / RangeOption / ChoiceOption / ColorOption`：具体类型。
- `ConfigItem[T]`：绑定到 store 的可观察值， emits `valueChanged(new_value)`。
- `ConfigGroup`：一组 `Option` 的命名空间。
- `ConfigStore`：持有 YAML 文档，500 ms 防抖 + 原子替换写入。

### 使用模式

```python
class MyConfig(ConfigGroup):
    enabled = BoolOption(True)
    opacity = RangeOption(90, 10, 100)


cfg = store.bind(MyConfig, "plugins.my_plugin")
cfg.opacity.valueChanged.connect(handler)
cfg.opacity.set(80)  # validated, persisted, emitted
```

### 持久化

- 路径：`settings.yaml`，位于平台用户配置目录。
- 写入：`tmp` 文件 → `os.replace`，失败时删除 tmp。
- 加载失败：备份为 `.broken-<timestamp>.yaml`，清空配置。

### 导出与导入

- `export_file(path)` 导出完整 YAML 快照，包含已绑定配置的默认值、尚未防抖落盘的修改，以及未识别插件的原始配置。
- `read_import_file(path)` 只读取并验证文件，不修改当前设置；拒绝非法类型、非有限数值、循环别名及不含应用设置的文档。
- `replace_for_restart(data)` 原子替换全部配置，成功后调用方必须立即重启；导入文件缺少的选项在下次启动时使用默认值。写入失败保留原设置，成功后阻止退出清理中的旧配置写回覆盖导入结果。

### INVARIANT

- `ConfigItem.set()` 必须在 GUI 线程调用。
- 非法值回退默认值并记录 warning；不会崩溃。
- 配置命名空间使用 `.` 分隔，如 `app.language`、`plugins.capture.mode`。

---

## 2.2 事件总线

### 核心类

- `EventBus`：维护 `event_type → list[Subscription]` 映射。
- `Subscription`：可 `cancel()` 取消订阅。

### 发布/订阅模式

```python
ctx.events.publish(GameForegroundChanged(True))
ctx.events.subscribe(FrameCaptured, on_frame)
```

### 线程模型

- `EventBus._dispatch` 是 `pyqtSignal(object)`，使用 `Qt.AutoConnection`。
- 从工作线程发布时自动排队到 GUI 线程。

### INVARIANT

- 事件类型推荐用 frozen dataclass。
- handler 异常被捕获并记录，不影响其它 handler。
- 插件应通过 `ctx.subscribe()` 而非直接 `EventBus.subscribe()`，以便停用时自动清理。

---

## 2.3 服务注册表

### 核心类

- `ServiceRegistry`：以 API 类型为键注册实现。
- `register(api, impl, owner)` / `unregister(api)` / `unregister_owner(owner)`。

### 使用模式

```python
# 提供方
ctx.provide(CaptureApi, _CaptureService(self))

# 消费方
capture = ctx.services.get(CaptureApi)  # 可能 None
capture = ctx.services.require(CaptureApi)  # 缺失抛 LookupError
```

### INVARIANT

- 一个 API 只能有一个实现；重复注册抛 `ValueError`。
- 服务变更通过 `serviceChanged` 信号广播；弱依赖消费方需监听此信号。
- 插件停用时 `PluginContext.release()` 会调用 `unregister_owner(plugin_id)`。

---

## 2.4 前台策略

### 核心类

- `GameWindowMonitor`：轮询前台窗口标题（Windows），macOS 视为始终前台。
- `ForegroundPolicy`：统一实现“仅在游戏时显示和检测”。

### 门控规则

| 门控 | 规则 |
|------|------|
| `display_allowed` | `not enabled OR game_foreground OR ui_active` |
| `input_allowed` | 与 `display_allowed` 相同 |
| `detection_allowed` | `not enabled OR game_foreground`（无 UI 例外） |

### UI 活跃来源

通过 `set_ui_active(source, active)` 维护集合：

- `main_window`：主界面可见且未最小化
- `tray_menu`：托盘菜单弹出
- `overlay_menu`：悬浮窗右键菜单
- `region_selection`：区域标定期间

### INVARIANT

- `ForegroundPolicy` 是悬浮窗可见性的**全局门控**，不是唯一条件。
- 悬浮窗自身隐藏原因优先；前台门控只能隐藏，不能显示。
- `detection_allowed` 没有 UI 例外，避免后台持续截图。

---

## 2.5 国际化

### 核心函数/类

- `discover_languages()` / `available_languages()`：从 `resources/i18n/*.yaml` 动态发现语言。
- `match_language(locale)`：系统 locale 到支持语言的映射。
- `Translator`：加载命名空间词条。
- `tr(key, **kwargs)`：核心词条翻译。

### 回退链

- 当前语言 → `zh_CN` → 键名本身。
- 教程：`当前语言 → zh_CN → en_US`。

### 命名空间

- 核心：`resources/i18n/<lang>.yaml`，通过 `tr()` 访问。
- 插件：`plugins/<id>/i18n/<lang>.yaml`，通过 `ctx.tr()` 访问。

### INVARIANT

- 核心词条必须覆盖每种语言且键与 `zh_CN` 一致。
- 插件 UI 词条只要求 `zh_CN` 完整；其他语言可以缺项并回退中文，已有词条的格式占位符必须与中文一致。教程至少提供 `zh_CN`。
- 地图名称表是例外：各正式语言的 `<语言>-names.csv` 必须覆盖 `zh_CN-names.csv` 的全部 ID，名称不得为空。
- 切换语言后提示重启生效。

---

## 2.6 路径与日志

### 路径模块

- `resource_path(*parts)`：包内资源路径。
- `user_data_dir()`：用户数据目录（settings.yaml、诊断图）。
- `log_dir()`：日志目录。
- 支持环境变量 `NIGHTREIGN_OVERLAY_DATA_DIR` 覆盖。

### 日志模块

- `get_logger(__name__)`：按模块名获取 logger。
- 禁止 `print`。
- 日志级别通过 `app_config.log_level` 控制。

---

## PATTERN：新增一个核心能力

1. 若需要持久化：在 `core/config.py` 定义 `ConfigGroup` 或在 `core/app_config.py` 扩展 `AppConfig`。
2. 若需要广播：在核心或相关模块定义 dataclass 事件类型。
3. 若需要被插件消费：在 `core/services.py` 注册为服务，或提供 API class 供插件在 `api.py` 中 re-export。
4. 保证 core 不 import ui 或 plugins。

## 常见修改场景

| 场景 | 应修改位置 |
|------|-----------|
| 新增配置类型 | `core/config.py` 新增 `Option` 子类 |
| 新增全局事件 | 定义 frozen dataclass；在发送方 `publish()` |
| 新增全局服务 | `core/services.py` 定义 API；在 `Application` 注册 |
| 调整前台策略 | `core/game_window.py` |
| 新增语言/词条 | `resources/i18n/<lang>.yaml` 或插件 `i18n/<lang>.yaml` |
