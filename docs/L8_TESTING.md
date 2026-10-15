# L8 · 测试策略

## 职责

保证核心逻辑、插件行为、UI 组件在重构和新增功能时不退化。

## 测试目录

[`tests/`](../tests/)

## 关键文件

| 文件 | 职责 |
|------|------|
| [`tests/conftest.py`](../tests/conftest.py) | pytest fixture（QApplication、临时配置目录等） |
| [`tests/feature_fakes.py`](../tests/feature_fakes.py) | 插件测试用的 fake 服务/后端 |

## 测试分类

### 核心单元测试

| 测试文件 | 覆盖内容 |
|---------|---------|
| `test_config.py` | 配置声明、绑定、持久化、回退、防抖 |
| `test_events_services.py` | 事件总线、服务注册表、跨线程投递 |
| `test_i18n.py` | 语言发现、回退链、系统 locale 匹配 |
| `test_plugin_manager.py` | 插件发现、拓扑排序、依赖解析、启停联动 |

### 插件测试

| 测试文件 | 覆盖内容 |
|---------|---------|
| `test_infrastructure_plugins.py` | capture/input/hud/region 基础行为 |
| `test_day_timer.py` | 阶段推进、快捷键、标定、HUD |
| `test_rain_timer.py` | 雨中状态机、颜色校准、HUD |
| `test_art_timer.py` | 绝招识别、状态机、HUD |
| `test_map_detect.py` | 选区、状态机、后台线程、快捷键、HUD 联动 |
| `test_map_terrain.py` | 地图图片特殊地形回归、算法阈值隔离、NCC 拒识 |
| `test_map_nightlord.py` | 夜王模板匹配样本准确率，隐藏样本只接受 unk.png（None） |
| `test_map_localization.py` | 地图名称表 i18n |
| `test_hp_marker.py` | 检测、标记位置、失败保持、前台门控 |
| `test_p2p_latency.py` | 服务状态、窗口布局、模拟 helper |
| `test_overlay.py` | 悬浮窗基类行为、可见性、位置持久化 |
| `test_overlay_activation.py` | 非激活点击 |
| `test_region_preview.py` | 区域预览 |
| `test_settings_reset.py` | 设置重置 |
| `test_tray_exit.py` | 托盘退出/隐藏行为 |

### 旧版对照测试

| 测试文件 | 覆盖内容 |
|---------|---------|
| `test_hp_marker_legacy_parity.py` | 血条检测与旧版逐帧比较 |
| `test_map_detect_legacy_parity.py` | 地图检测与旧版输出/绘制比较 |

- 隔离加载旧版源码；缺少旧版目录时自动跳过。
- 保证重写算法与旧版一致。

地图特殊地形样本、文件名 ground truth 规则和测试脚本分工见 [`MAP_DETECT_TESTING.md`](./MAP_DETECT_TESTING.md)。

## 运行测试

```bash
# Qt offscreen 平台
export QT_QPA_PLATFORM=offscreen
pytest

# lint / format / diff
ruff check .
ruff format --check .
git diff --check
```

## INVARIANT

- Qt 相关测试在 `QT_QPA_PLATFORM=offscreen` 下运行。
- 复杂 fixture 必须注册核心服务，避免定时器回调 `require()` 失败导致进程 abort。
- 核心逻辑（配置、事件、服务、依赖解析）必须有单元测试。
- 提交前必须通过 `ruff check`、`ruff format --check`、`git diff --check`。

## PATTERN：为新增插件写测试

1. 在 `tests/test_<plugin_id>.py` 创建测试模块。
2. 使用 `conftest.py` 中的 fixture 构造 `PluginContext` 和 fake 服务。
3. 测试 `on_load()` 后的配置绑定、`on_activate()` 后的资源注册。
4. 测试事件处理逻辑（可用 `HotkeyApi.trigger_for_test()` 模拟快捷键）。
5. 测试 `on_deactivate()` 后资源是否释放。

## 常见修改场景

| 场景 | 应查看/修改 |
|------|------------|
| 新增核心功能测试 | `tests/test_config.py` / `test_events_services.py` / `test_i18n.py` |
| 新增插件测试 | `tests/test_<plugin_id>.py` |
| 新增 UI 测试 fixture | `tests/conftest.py` + `tests/feature_fakes.py` |
| 调整 ruff 规则 | `pyproject.toml` `[tool.ruff]` |
| 调整 pytest 配置 | `pyproject.toml` `[tool.pytest.ini_options]` |
