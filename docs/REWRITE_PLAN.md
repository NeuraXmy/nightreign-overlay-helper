# 黑夜君临悬浮助手 · 重写计划

## 1. 背景与目标

旧版（`nightreign-overlay-helper`）功能完整，但存在以下问题，本次重写逐一对应解决：

| # | 旧版问题 | 重写方案 |
|---|---------|---------|
| 1 | 手写代码风格不统一 | `ruff`（lint + format）统一风格；全量类型标注；模块/类 docstring 规范；`logging` 分模块 logger 替代全局 `info()/error()` |
| 2 | 功能互相复杂依赖，`Updater` 是巨型协调者 | **核心底座 + 插件** 架构。插件之间只通过 *服务契约（Service API）* 与 *类型化事件（Event Bus）* 交互，依赖在 manifest 中显式声明，由插件管理器做拓扑排序与联动启停 |
| 3 | UI 难看 | 引入 [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)（PyQt6 版 `PyQt6-Fluent-Widgets`），主界面使用 `FluentWindow` |
| 4 | 无多语言 | 自研轻量 i18n：YAML 词条 + 命名空间（核心 / 每个插件各自一份），支持 简中 / 繁中 / English / 日本語，同时加载 qfluentwidgets 自带翻译 |
| 5 | 设置菜单平铺 | 设置窗口升级为 **主界面**：首页展示概况；用户可见的功能插件使用独立页面；基础能力按设置范围归入通用设置或隐藏；通用设置与关于放在导航底部 |

非目标（本阶段不做）：修改游戏内存、网络服务端、Linux 正式支持。

平台策略：**Windows 为主要目标平台**；自动悬浮窗模式优先使用旧版式无边框透明悬浮窗，若平台合成器显示异常，用户可在通用设置中显式切换为「普通窗口」作为 fallback。

> **旧版行为复原优先。** 每次实现或调整功能前，必须先全面审阅旧版 `nightreign-overlay-helper` 的对应实现、配置、交互和边界行为；重写时以完整复原既有行为为第一目标，而不是先行简化、优化或重新设计。只有确认旧版存在明确缺陷、安全风险或平台不兼容时才允许偏离，并须在实现记录中说明差异、理由和影响。

## 2. 总体架构

```
┌───────────────────────────────────────────────────────────┐
│                        UI Shell                           │
│  MainWindow(FluentWindow) · HomePage · PluginPage(设置/教程) │
│  SettingsPage · AboutPage · Tray · OverlayWindow 基类       │
├───────────────────────────────────────────────────────────┤
│                     Plugin System                         │
│  PluginManifest · Plugin · PluginContext · PluginManager   │
├───────────────────────────────────────────────────────────┤
│                         Core                              │
│  paths · log · config · i18n · events · services          │
│  single_instance · game_window                            │
├───────────────────────────────────────────────────────────┤
│                    Platform Backend                       │
│  windows (ctypes / user32)   ·   generic (macOS 调试)       │
└───────────────────────────────────────────────────────────┘
```

依赖方向严格自上而下：Core 不依赖 UI 与插件；插件只依赖 Core / UI 公共组件 / 其它插件公开的 `api` 模块。

### 2.1 目录结构

```
src/nightreign_overlay/
├── __main__.py / app.py      # 启动入口与应用生命周期
├── meta.py                   # 应用常量（ID、版本、游戏窗口标题…）
├── core/                     # 与 UI 无关的基础设施
├── platforms/                # 平台差异封装（置顶、前台窗口检测、管理员权限…）
├── plugin/                   # 插件协议与管理器
├── ui/                       # 主界面、通用组件、悬浮窗基类
├── resources/                # 核心 i18n、图标
└── plugins/                  # 内置插件，每个插件一个子包
    └── <plugin_id>/
        ├── __init__.py       # 导出 Plugin 子类
        ├── api.py            # （可选）对外公开的服务契约 —— 其它插件只能 import 这里
        ├── config.py         # 配置声明
        ├── plugin.py         # 生命周期实现
        ├── i18n/<lang>.yaml  # 插件自己的词条
        └── tutorial/<lang>.md# 插件教程（Markdown，可引用同目录图片）
```

## 3. 插件系统（解决“功能互相依赖”）

### 3.1 插件生命周期

```
discovered ──load()──▶ loaded ──activate()──▶ active
                         ▲                       │
                         └──────deactivate()─────┘
```

- **loaded**：读取 manifest、绑定配置、加载词条。所有已发现插件都会进入此状态，因此即使功能关闭，其设置页 / 教程依然可以浏览与修改。
- **active**：真正开始工作（创建悬浮窗、注册服务、订阅事件、启动定时器）。
- 启用状态持久化在配置 `plugin_manager.enabled.<id>`；用户在页面头部或首页卡片上开关，**无需重启**。

### 3.2 依赖声明与联动

```python
manifest = PluginManifest(
    id="map_detect",
    requires=("capture", "hud"),  # 强依赖：缺失/未启用则本插件无法启用
    optional=("day_timer",),  # 弱依赖：存在则增强功能，不存在也能运行
)
```

- 管理器对 `requires + optional` 做拓扑排序，检测循环依赖与缺失依赖（缺失强依赖的插件标记为 `unavailable` 并在 UI 中提示原因）。
- **启用插件** → 自动先启用其所有强依赖。
- **停用插件** → 自动先停用依赖它的插件（逆拓扑序），并通过 InfoBar 告知用户。
- 弱依赖在运行期可能出现/消失，消费方通过 `ServiceRegistry.serviceChanged` 信号感知。

### 3.3 插件间通信的两种方式

1. **服务契约（请求 / 查询 / 有状态能力）**
   提供方在 `plugins/<id>/api.py` 中定义接口（QObject + 信号 或 Protocol）与数据类，激活时
   `ctx.services.register(DayTimerApi, impl)`；消费方 `ctx.services.get(DayTimerApi)`。
   消费方**只允许 import 提供方的 `api.py`**，不允许 import 其内部实现，从而把耦合面压缩到一个稳定文件。
2. **类型化事件总线（广播事实）**
   以 dataclass 作为事件类型：`ctx.events.publish(GameForegroundChanged(True))`、
   `ctx.events.subscribe(GameForegroundChanged, handler)`。跨线程发布会自动排队到主线程投递。
   插件停用时其订阅自动解除（`PluginContext` 记录订阅并在 deactivate 后清理）。

### 3.4 旧版依赖关系的拆解示例

| 旧版隐式依赖 | 新版处理方式 |
|------------|------------|
| 所有 detector 各自截图、重复转换整帧 | `capture` 基础插件每个检测 tick 只截一帧，发布 `FrameCaptured`；各检测插件订阅后裁剪自己的区域 |
| 缩圈 / 雨中 / 绝招 共用一个悬浮窗 | `hud` 基础插件提供 `HudApi.add_widget(...)`，各功能向同一 HUD 悬浮窗贡献自己的进度条组件，顺序可配置 |
| 地图识别依赖缩圈时间 | `map_detect` 对 `day_timer` 声明 `optional`，通过 `DayTimerApi` 读取阶段 / 订阅 `DayPhaseChanged` |
| 雨中检测与血条检测共享 HLS 颜色配置 | 颜色校准作为 `hp_color` 能力由一个插件提供服务，其余插件通过 API 读取 |
| 快捷键散落在各处 | `input` 基础插件提供 `HotkeyApi.register(action_id, default_combo, callback)`，统一在其设置页编辑所有快捷键 |
| 检测区域标定 | `region` 服务：`RegionApi.request_region(key)` 统一弹出截图选区窗口，结果存入调用方配置 |

### 3.5 插件分层规划

- **基础插件（infrastructure）**：`capture`（截图引擎 / 检测频率 / 仅游戏前台检测）、`input`（全局热键 / 手柄）、`hud`（共享悬浮窗）、`region`（区域标定）。默认启用，首页中归类为“基础功能”。
- **功能插件（feature）**：`day_timer` 缩圈倒计时、`rain_timer` 雨中冒险计时、`map_detect` 地图识别、`hp_marker` 血条比例标记、`art_timer` 绝招倒计时、`p2p_latency` 队友延迟。
- **调试插件**：`overlay_test` 测试悬浮窗（本阶段实现，用于验证底座、悬浮窗与跨平台行为）。

### 3.6 设置范围与用户入口

`PluginManifest.settings_scope` 独立于运行时的 `kind` 与依赖关系，决定插件设置在 UI 中的入口：

- `page`：创建独立导航页与首页卡片，适用于用户直接使用的功能插件；这是默认值。
- `general`：不创建导航页或首页卡片，其 `create_settings_widget()` 合并到通用设置页，适用于有少量全局选项的基础能力。
- `hidden`：不创建设置入口、导航页或首页卡片；功能插件在自身页面按需暴露其操作入口，例如“标定区域”或功能自身的快捷键。

用户可见的插件分组顺序固定为 **功能 → 基础 → 调试**。该顺序只影响导航和首页，插件运行时仍按依赖拓扑排序启停。

P2 的范围：`capture` 与 `hud` 使用 `general`；`input` 与 `region` 使用 `hidden`。因此基础服务仍独立加载、启停和提供 API，但不增加用户的页面理解成本。首页的插件卡片与“已启用插件数”也只统计 `settings_scope=page` 的用户可见插件，避免将后台基础服务误认为用户需要管理的功能。

插件的首次启用状态按 `kind` 决定：功能插件与基础插件默认启用，调试插件默认关闭；manifest 可显式覆盖默认值。基础插件由应用托管，始终启用且不接受用户的开关请求，即使遗留配置中记录为关闭也不生效。

### 3.7 悬浮窗拆分策略

插件边界和窗口边界不要求一一对应：业务能力按插件拆分，窗口则按展示职责组合。更新频率、定位规则、交互方式或显示时机差异明显的内容使用独立窗口；视觉形式一致的小型状态信息组合到共享 HUD，避免屏幕上散落多个窗口。

规划为三个展示容器：

| 窗口 | 内容 | 拆分依据 |
|-----|------|---------|
| `HpMarkerOverlay` | 血量阈值标记 | 动态跟随血条位置、高频更新、固定鼠标穿透，不使用普通的拖动位置持久化 |
| `MapInfoOverlay` | 地图识别结果、水晶布局、识别状态 | 显示区域较大，只在地图识别期间出现，并有独立的切换交互 |
| `HudOverlay` | 缩圈、雨中、绝招等倒计时或紧凑状态 | 视觉形式和更新频率接近，共享位置、缩放、透明度、排列方向与间距 |

`hud` 是只负责容器和布局的基础插件，不直接依赖或导入任何功能插件。`day_timer`、`rain_timer`、`art_timer` 等功能插件通过稳定的 `HudApi` 注册和移除自己的组件；组件的业务状态及显示内容仍由对应功能插件管理。插件停用时，其 HUD 组件必须随插件上下文自动移除，其他组件和 HUD 窗口继续运行。

依赖关系按以下方式声明：

- `day_timer`、`rain_timer`、`art_timer` 对 `hud` 使用强依赖，需要显示时向 `HudApi` 注册组件。
- `map_detect` 创建并管理独立的 `MapInfoOverlay`，对 `capture` 使用强依赖，对 `day_timer` 使用弱依赖；缩圈阶段只用于优化地图识别时机。
- `hp_marker` 创建并管理独立的 `HpMarkerOverlay`，只依赖截图或血条检测能力，不依赖 HUD 和地图插件。
- `hud`、`map_detect`、`hp_marker` 都通过核心 `OverlayManager` 接入统一的置顶、显示模式和游戏前台可见性管理。

配置归属保持在能力拥有者一侧：`hud` 保存共享窗口的位置、缩放、透明度、排列与间距；倒计时内容和检测参数保存在各自功能插件；地图窗口配置归 `map_detect`；血量阈值、颜色和线宽归 `hp_marker`。这样既能共享窗口基础能力，也不会把功能配置重新耦合到一个巨型 Overlay 插件中。

### 3.8 P2 实施约束

- **实现前先完整审阅旧版，复原优先。** 每项功能须先核对旧版的代码路径、配置项、交互流程、视觉细节和边界行为，再开始重写；不得因局部观察而擅自简化、优化或改变用户已习惯的行为。仅在确认旧版存在明确缺陷、安全风险或平台不兼容时调整，并在实现记录中单独说明差异、理由和影响。
- `capture` 是唯一的周期性截图提供者：功能插件先订阅 `FrameCaptured`，再以自己的插件 ID 调用 `CaptureApi.acquire_stream(owner)` 申请帧流，并在 `PluginContext.on_cleanup()` 中调用 `release_stream(owner)`。首个租约启动定时截图，最后一个租约释放后立即停止；`capture_now()` 仅用于单次请求。这样没有截图消费者时不会定时抓取屏幕，多个消费者仍共享同一完整帧后各自裁剪区域。
- HDR 图像处理是 `capture` 的统一设置（`plugins.capture.hdr_processing`），不再由各功能插件各自配置。`capture` 不修改共享帧，只在 `FrameCaptured.hdr` 上标记截图时的开关状态；各检测插件按旧版约定自行选择处理方式（如 DAY 模板匹配用 `capture.api.hdr_to_sdr()`，血条/雨中颜色采样保持原图），新的通用转换函数也统一放在 `capture.api`。
- 平台差异与外设能力必须保持可调用的服务契约和可注入测试接口。macOS 使用 Qt 截图作开发调试降级；“自动”悬浮窗模式优先使用透明悬浮窗，若 macOS 合成器存在显示问题，用户可显式切换普通窗口；Windows 原生 DLL 打包、`pynput` 权限行为和 pygame 手柄实机验证在 Windows 环境执行。
- 在完整 worker 线程模型迁移前，DAY 标定期间暂停该插件的模板匹配；识别前把用户选区缩放到旧版同样的模板标准高度（30 px），防止误框大区域时在 GUI 线程进行高分辨率匹配而持续卡顿。
- 功能插件使用 HUD 时，调用方在自己的 `PluginContext` 中注册清理回调移除组件，保证热停用不会影响其他 HUD 内容。`HudOverlay` 在添加组件后重新激活布局、按最终 size hint 调整窗口并显式展示/置顶，避免初始空容器尺寸导致内容不可见。HUD 提供独立启用开关，关闭时调用窗口隐藏流程而不是将透明度设为零，确保不留下透明顶层窗口。`day_timer` 还原旧版固定 400px、按四段时长比例分配的蓝紫色分段进度条和带阴影白色粗体文字；容器基准尺寸必须包含全部边距，缩放时内容的宽度、进度条高度、文字、圆角和间距同步缩放。HUD 右键菜单仅提供打开主界面与安全退出程序。

## 4. 配置系统

- 声明式配置：插件定义 `ConfigGroup` 子类，类属性使用 `BoolOption / RangeOption / ChoiceOption / Option` 描述默认值与校验规则；实例化后每一项为带 `valueChanged` 信号的 `ConfigItem`。
- 存储：单一用户配置文件 `settings.yaml`（平台用户配置目录），按命名空间分区：`app.*`、`plugin_manager.*`、`plugins.<id>.*`。
- 写入：修改后 500 ms 防抖 + 原子替换写入，退出时强制落盘；非法值回退默认值并记录 warning。
- 迁移旧版 `config.yaml` 时，用户可能需要调整的检测阈值、时间偏移等参数归入功能插件的“高级选项”；仅保留不应由用户修改的内部常量于代码或 `plugins/<id>/tuning.yaml`。
- 设置卡片（`ui/components/setting_cards.py`）直接绑定 `ConfigItem`，双向同步，不依赖 qfluentwidgets 的全局 `qconfig`（其内置卡片会写入 cwd 下的 `config/config.json`）。功能页中的快捷键卡通过 `HotkeyApi` 读取和保存绑定，避免暴露 input 基础插件页面；该 API 的绑定读写能力在 input 的 `on_load()` 即注册，以满足主窗口在插件激活前构造设置页的时序，物理监听仍只在 `on_activate()` 启动。绑定存为 `{device, keys}`，首次读取旧版 `ctrl+shift+d` 字符串时自动迁移；录制使用独立模态窗口，实时展示输入、首个非空输入锁定 keyboard / mousebutton / joystick 设备类型，并提供清空、取消和确认。显示顺序固定为 Ctrl、Alt、Shift、Cmd、普通键；macOS 记录 `pynput` 上报的实际 Ctrl/Cmd 物理键标识，不推断或转换用户的系统修饰键交换设置，以保证录制和运行时匹配一致。

## 5. 多语言（i18n）

- 语言：`zh_CN`（默认/回退）、`zh_TW`、`en_US`、`ja_JP`；“跟随系统”自动选择。
- **当前阶段仅编写 `zh_CN` 词条。** 其他语言使用回退链显示中文，待后续多语言完善阶段再补充翻译。
- 词条文件为嵌套 YAML，加载后展平为 `a.b.c` 键；`tr("home.title", name=...)` 支持 `str.format` 插值。
- 命名空间：核心词条位于 `resources/i18n`；插件词条位于各自目录，通过 `ctx.tr()` 访问，互不冲突。
- 回退链：当前语言 → `zh_CN` → 键名本身（便于发现漏翻）。
- 教程使用 `tutorial/<lang>.md`，同样遵循回退链。
- 切换语言后提示重启生效（保持实现简单可靠）。

## 6. UI 设计

- **主界面 `MainWindow(FluentWindow)`**
  - 顶部：首页
  - 中部（可滚动）：仅 `settings_scope=page` 的插件作为导航项，按 功能 / 基础 / 调试 分组
  - 底部：通用设置（包含 `settings_scope=general` 的插件设置）、关于
- **首页**：应用信息横幅（名称 / 版本 / 平台）、运行状态卡片（游戏窗口是否前台、悬浮窗模式、已启用插件数）、`settings_scope=page` 插件的快捷开关列表。
- **插件页**：页头（图标 / 名称 / 描述 / 启用开关 / 依赖状态），下方 `SegmentedWidget` 选项卡：「设置」「教程」，插件可以追加自定义选项卡。
- **通用设置**：语言、主题（浅色 / 深色 / 跟随系统）、主题色、悬浮窗显示模式（自动 / 悬浮窗 / 普通窗口）、关闭主界面时最小化到托盘、`settings_scope=general` 的插件设置、日志级别、打开配置 / 日志目录。
- **托盘**：显示主界面、退出；双击托盘图标打开主界面。
- **悬浮窗基类 `OverlayWindow`**：统一处理无边框 / 透明 / 置顶 / 鼠标穿透 / 不抢焦点 / 拖动 / 位置持久化 / 透明度 / “仅游戏前台显示”，以及普通窗口 fallback。

## 7. 平台层

| 能力 | Windows | macOS（调试） |
|-----|---------|--------------|
| 无边框透明置顶悬浮窗 | Qt flags + `SetWindowPos(HWND_TOPMOST)` 周期性重申（防止全屏游戏抢占） | Qt flags + `WA_MacAlwaysShowToolWindow`；异常时切换普通窗口 |
| 鼠标穿透 | `WindowTransparentForInput`（WS_EX_TRANSPARENT） | `WindowTransparentForInput` |
| 前台窗口标题 | `GetForegroundWindow` + `GetWindowTextW`（ctypes，去除 pywin32 依赖） | 不支持，视为“游戏在前台” |
| 管理员权限检测 / 提权重启 | `IsUserAnAdmin` / `ShellExecuteW(runas)` | 不适用 |
| 截图 | MaaWin32Screencap.dll（后续 `capture` 插件迁移） | Qt `QScreen.grabWindow` 调试实现 |

## 8. 代码规范

- Python ≥ 3.11（发布构建使用 3.13），`from __future__ import annotations`。
- `ruff format` + `ruff check`（规则集：E, F, W, I, UP, B, SIM, N, RUF），行宽 110。
- 命名：模块 / 函数 / 变量 `snake_case`，类 `PascalCase`；Qt 信号使用 `camelCase` 与 Qt / qfluentwidgets 保持一致（如 `valueChanged`）。
- 每个模块顶部 docstring 说明职责；公共 API 写 docstring；注释解释“为什么”而不是“做什么”。
- 日志：`log = get_logger(__name__)`，禁止 `print`。
- 测试：`pytest`，核心逻辑（配置、i18n、依赖解析、事件总线）必须有单元测试；Qt 相关测试在 `QT_QPA_PLATFORM=offscreen` 下运行。

## 9. 路线图

| 阶段 | 内容 | 状态 |
|-----|------|-----|
| P0 | 计划文档 | ✅ |
| P1 | 底座：core / platform / plugin / 主界面 / 托盘 / 悬浮窗基类 / i18n；`overlay_test` 测试插件；单元测试 | ✅ 本次完成 |
| P2 | 基础插件：`capture`（迁移 MaaWin32Screencap）、`input`（pynput + pygame 热键）、`region`（区域标定）、`hud` | 🚧 进行中：服务契约、Qt 降级实现和单元测试已完成；Windows DLL 打包与真实手柄验证留待 Windows 环境 |
| P3 | 功能插件迁移：`day_timer`、`rain_timer`、`art_timer` | 待开始 |
| P4 | `map_detect`、`hp_marker`、`p2p_latency`（含 NightreignP2PHelper 原生组件） | 待开始 |
| P5 | 打包发布：PyInstaller spec、GitHub Actions、管理员权限提示、旧版配置迁移、自动更新检查 | 待开始 |

## 10. 风险与应对

- **全屏游戏遮挡悬浮窗**：保持旧版“无边框窗口化”使用建议；周期性重申 TOPMOST。
- **qfluentwidgets 版本变动**：锁定次版本范围（`>=1.11,<1.12`），UI 公共组件封装在 `ui/components`，减少直接散用。
- **插件热启停导致资源泄漏**：`PluginContext` 统一托管订阅、服务注册、悬浮窗与定时器，deactivate 时自动回收。
- **跨线程访问 UI**：检测逻辑在工作线程，结果一律通过信号 / 事件总线回到主线程更新 UI。
