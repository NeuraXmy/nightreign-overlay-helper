# L7 · UI 层

## 职责

构建主界面、插件页、通用设置页、悬浮窗基类、设置卡片、主题/托盘。

## 关键文件

| 文件 | 职责 |
|------|------|
| [`src/nightreign_overlay/ui/main_window.py`](../src/nightreign_overlay/ui/main_window.py) | `FluentWindow` 主窗口、导航、插件页初始化 |
| [`src/nightreign_overlay/ui/pages/home.py`](../src/nightreign_overlay/ui/pages/home.py) | 首页 |
| [`src/nightreign_overlay/ui/pages/plugin_page.py`](../src/nightreign_overlay/ui/pages/plugin_page.py) | 插件页（设置/教程/重置） |
| [`src/nightreign_overlay/ui/pages/faq.py`](../src/nightreign_overlay/ui/pages/faq.py) | 常见问题图文页 |
| [`src/nightreign_overlay/ui/pages/settings.py`](../src/nightreign_overlay/ui/pages/settings.py) | 通用设置页 |
| [`src/nightreign_overlay/ui/components/diagnostic_export.py`](../src/nightreign_overlay/ui/components/diagnostic_export.py) | 问题描述、图片附件和后台导出 ZIP，见 [DIAGNOSTIC_EXPORT.md](DIAGNOSTIC_EXPORT.md) |
| [`src/nightreign_overlay/ui/pages/about.py`](../src/nightreign_overlay/ui/pages/about.py) | 关于页 |
| [`src/nightreign_overlay/ui/overlay.py`](../src/nightreign_overlay/ui/overlay.py) | `OverlayWindow` 基类 + `OverlayManager` |
| [`src/nightreign_overlay/ui/components/setting_cards.py`](../src/nightreign_overlay/ui/components/setting_cards.py) | 绑定 ConfigItem 的设置卡片 |
| [`src/nightreign_overlay/ui/components/overlay_settings.py`](../src/nightreign_overlay/ui/components/overlay_settings.py) | 悬浮窗通用设置段 |
| [`src/nightreign_overlay/ui/components/page.py`](../src/nightreign_overlay/ui/components/page.py) | `ScrollPage` / `SettingSection` |
| [`src/nightreign_overlay/ui/components/plugin_widgets.py`](../src/nightreign_overlay/ui/components/plugin_widgets.py) | `PluginSwitch` 等 |
| [`src/nightreign_overlay/ui/components/reset_button.py`](../src/nightreign_overlay/ui/components/reset_button.py) | 页面重置按钮 |
| [`src/nightreign_overlay/ui/theme.py`](../src/nightreign_overlay/ui/theme.py) | 主题、图标映射 |
| [`src/nightreign_overlay/ui/tray.py`](../src/nightreign_overlay/ui/tray.py) | 托盘图标与菜单 |

---

## 7.1 主窗口

### MainWindow

- `FluentWindow` 子类，使用普通窗口层级，不设置 `WindowStaysOnTopHint`。
- 主窗口层级不参与识别门控；窗口在前台时沿用既有 `ForegroundPolicy.detection_allowed` 规则。
- 左侧导航顺序：首页 → 功能插件页 → 基础插件页 → 调试插件页 → 常见问题 → 通用设置 → 关于。
- 导航项分组由 `PLUGIN_KIND_DISPLAY_ORDER` 决定。
- 关闭事件默认隐藏到托盘；`prepare_quit()` 后接受关闭。

### 关闭行为

```python
def closeEvent(self, event):
    if self._quitting:
        event.accept()
        return
    event.ignore()
    self.hide()
    self.hiddenToTray.emit()
```

### presenceChanged 信号

表示窗口是否在屏幕且未最小化，用于 `ForegroundPolicy.set_ui_active("main_window", present)`。

---

## 7.2 页面

### HomePage

- Banner（应用名/版本/渐变背景），与关于页共用；高度为原 168 像素的 60%（取整为 101 像素），文字垂直居中。
- 状态卡片：游戏前台、悬浮窗模式、已启用插件数。
- 插件快捷开关列表（仅 `settings_scope=PAGE`）。

### PluginPage

- 页头：图标、名称、描述、状态标签、启用开关。
- 选项卡：设置 / 教程。
- 设置选项卡有重置按钮；重置只在设置选项卡可见。
- 教程使用 `QTextBrowser` 加载本地化 Markdown，相对图片路径自动解析。

### FaqPage

- 导航位于通用设置上方，使用问号图标。
- 使用与插件教程相同的 `TextBrowser` 加载本地化 Markdown，支持标题、列表、外链和相对路径图片。
- 内容放在 `src/nightreign_overlay/resources/faq/<语言>.md`，缺少对应语言时按中文、英文顺序回退。
- 图片可放在 FAQ 目录下，例如 `images/example.png`，在 Markdown 中写 `![说明](images/example.png)`；资源随应用打包。

### SettingsPage

- 通用设置：语言、主题、主题色、悬浮窗模式、前台门控、启动最小化、日志级别。
- 嵌入 `settings_scope=GENERAL` 的插件设置（capture、hud）。
- 打开数据目录/日志目录。
- 高级组中的“管理设置文件”卡片提供“导入”“导出”两个按钮，管理全部设置的 YAML 文件。导入先验证内容，再提示当前所有设置将丢失；确认并导入成功后立即重启。导出包含默认设置，文件使用 UTF-8 编码；音频等外部文件仅保存路径。
- 语言切换提示重启，并提供重启按钮。

---

## 7.3 悬浮窗基类

### OverlayManager

- 持有所有已注册 `OverlayWindow`。
- 监听 `overlay_mode` 变化 → 对所有窗口 `apply_window_mode()`。
- 监听 `ForegroundPolicy.changed` → 对所有窗口 `update_visibility()`。
- 每 1 秒 `ensure_topmost()` 重申置顶。

### OverlayWindow

统一处理：

- 无边框透明模式 vs 普通窗口模式
- 置顶、鼠标穿透、不抢焦点
- 拖动、位置持久化
- 透明度、缩放
- 前台门控

### 可见性规则

```python
def should_be_visible(self) -> bool:
    if not self._requested:
        return False
    if self.manager.transparent_mode:
        return self.manager.foreground.display_allowed
    return True
```

子类叠加自身条件：`return self_condition and super().should_be_visible()`。

### 输入模式

| 模式 | 行为 |
|------|------|
| `normal` | 可拖动 |
| `locked` | 不可拖动 |
| `passthrough` | 鼠标穿透（透明模式添加 `WindowTransparentForInput`） |

### 位置持久化

- 保存左上角坐标 + 保存时的宽度。
- 缩放/内容变化时按锚点（center/right）调整 x 坐标并持久保存。
- 尺寸变化时显式移动窗口，不依赖配置变更信号；启动时临时宽度恢复到保存宽度，可能得到与原配置相同的坐标，此时配置不会发出信号。
- 重置位置时通过 live window 计算默认坐标并立即写入配置。

### INVARIANT

- 不要直接调用 `show()` / `hide()`，应使用 `show_overlay()` / `hide_overlay()`。
- 不要用透明度 0 代替隐藏。
- 普通窗口模式豁免前台门控。
- 子类 `should_be_visible()` 必须以 `and super().should_be_visible()` 结尾。

---

## 7.4 设置卡片

### 卡片类型

| 卡片 | 绑定类型 | 用途 |
|------|---------|------|
| `ConfigSwitchCard` | `BoolOption` | 开关 |
| `ConfigChoiceCard` | `ChoiceOption` | 下拉选择 |
| `ConfigRangeCard` | `RangeOption[int]` | 整数滑块 |
| `ConfigDoubleSpinCard` | `RangeOption[float]` | 浮点计数器 |
| `ConfigColorCard` | `ColorOption` | 颜色选择 |
| `HotkeySettingCard` | 热键绑定 | 打开录制对话框 |
| `MultiButtonSettingCard` | 无配置 | 一个卡片多个操作按钮 |

音频设置卡片 AudioSettingCard 位于 ui/components/audio_settings.py，绑定独立 AudioCueConfig，提供音量滑块、本地文件选择／更换／清空、浮点秒数和立即测试播放。audio_section 构建功能页末尾的独立分组。

### HotkeySettingCard

- 左侧显示标题/描述。
- 中间可放 `accessories`（如 `RegionStatus`）和 `actions` 按钮。
- 右侧大按钮打开 `_HotkeySettingDialog`。

### _HotkeySettingDialog

- 模态录制窗口。
- 首个非空输入锁定设备类型。
- 只响应“增加按键”的状态；松开不会覆盖绑定。
- 提供清空、取消、确认。

### INVARIANT

- 卡片直接绑定 `ConfigItem`，双向同步。
- qfluentwidgets 自带卡片绑定全局 `qconfig`，会写到工作目录 `config/config.json`，因此不使用。

---

## 7.5 主题与托盘

### theme.py

- `app_icon()`：应用图标。
- `fluent_icon(name)`：将 `manifest.icon` 字符串映射为 `FluentIcon`。
- `apply_theme(config)`：应用主题/主题色。

### tray.py

- 菜单：显示/隐藏主界面、退出。
- 双击托盘图标打开主界面。
- 菜单显示期间设置 `ForegroundPolicy.set_ui_active("tray_menu", True)`。

---

## PATTERN：新增一个悬浮窗

```python
class MyOverlay(OverlayWindow):
    position_anchor = "center"  # 或 "right"

    def __init__(self, manager, config, ...):
        super().__init__(manager, config, title, QSize(width, height))
        # 初始化内容

    def paint_overlay(self, painter: QPainter):
        # 在 base_size 坐标系内绘制
        ...

    def should_be_visible(self) -> bool:
        return self._my_condition and super().should_be_visible()
```

## 常见修改场景

| 场景 | 应修改位置 |
|------|-----------|
| 调整主窗口导航/关闭行为 | `ui/main_window.py` |
| 调整首页布局 | `ui/pages/home.py` |
| 调整插件页选项卡/重置 | `ui/pages/plugin_page.py` |
| 修改常见问题图文 | `resources/faq/`（内容）、`ui/pages/faq.py`（页面） |
| 调整通用设置 | `ui/pages/settings.py` |
| 调整悬浮窗通用行为 | `ui/overlay.py` |
| 新增设置卡片类型 | `ui/components/setting_cards.py` |
| 调整悬浮窗设置段 | `ui/components/overlay_settings.py` |
| 调整主题/图标 | `ui/theme.py` |
| 调整托盘菜单 | `ui/tray.py` |
