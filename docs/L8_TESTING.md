# L8 · 测试策略

## 职责

保证核心逻辑、插件行为、UI 组件在修改时不退化。测试按功能归类，运行入口仍为仓库根目录。

## 目录结构

```text
tests/
├── conftest.py              # 全局 fixture：QApplication、临时数据目录、ConfigStore
├── core/                    # 配置、事件/服务、i18n、插件管理器
├── plugins/                 # 功能及基础设施插件
│   └── map_detect/          # 地图状态机、手动筛选、地形/夜王、POI CNN
├── ui/                      # 悬浮窗、FAQ 图文、设置重置、托盘退出
├── platforms/               # 原生平台行为（当前为 macOS 悬浮窗非激活）
├── legacy/                  # 保留的血条旧版对照测试
├── support/                 # 共享 fake、Qt 工具、仓库/样本路径
└── data/map_detect/         # Git 跟踪的地图截图，位置保持稳定
```

每个测试分类都是 Python 包。共享工具通过 `tests.support.*` 导入；测试之间不互相导入，也不导入 `conftest.py` 中的普通函数。全局 fixture 由 pytest 自动发现。

## 分类与覆盖

| 目录 | 测试模块 | 覆盖内容 |
|------|----------|----------|
| `core/` | `test_config.py`、`test_events_services.py`、`test_i18n.py`、`test_plugin_manager.py` | 配置、事件/服务、翻译、插件依赖与生命周期 |
| `plugins/` | `test_capture_backends.py`、`test_infrastructure_plugins.py`、`test_region_preview.py` | 截图后端、输入/HUD/区域服务、区域预览 |
| `plugins/` | `test_capture_multiscreen.py`、`test_capture_diagnostic.py` | Windows/macOS 四方向副屏、负坐标、混合 DPI、DLL 客户区、标定/预览/地图叠加坐标一致性 |
| `plugins/` | `test_art_timer.py`、`test_day_timer.py`、`test_rain_timer.py` | 计时插件识别、状态机、快捷键、HUD |
| `plugins/` | `test_hp_marker.py`、`test_p2p_latency.py` | 血条标记、P2P 服务与窗口布局 |
| `plugins/map_detect/` | `test_map_detect.py`、`test_manual_catalog.py` | 地图状态机、设置、后台任务、手动筛选与候选约束 |
| `plugins/map_detect/` | `test_map_terrain.py`、`test_map_nightlord.py` | 地形与夜王标注截图回归 |
| `plugins/map_detect/` | `test_poi_cnn.py`、`test_map_localization.py` | ONNX CPU 单点/批量推理、类别约束、14 张地图 ID 验收、名称本地化 |
| `ui/` | `test_overlay.py`、`test_settings_reset.py`、`test_tray_exit.py` | 悬浮窗、设置重置、托盘与应用退出 |
| `ui/` | `test_faq.py` | FAQ Markdown、相对图片路径、语言回退、首页/关于页紧凑头图 |
| `platforms/` | `test_overlay_activation.py` | macOS 原生非激活窗口行为 |
| `legacy/` | `test_hp_marker_legacy_parity.py` | 血条检测与旧版逐帧比较，旧版目录缺失时跳过 |

早期悬浮窗调试插件及其专属生命周期测试已删除；通用悬浮窗和共享 HUD 的行为测试保留在 `ui/test_overlay.py`，插件发现测试验证正式内置插件及调试插件不再被发现。

地图旧版逐像素/评分对照测试已删除；地图识别通过标注截图、生产部署推理和状态机测试验证。样本规则与复测命令见 [`MAP_DETECT_TESTING.md`](./MAP_DETECT_TESTING.md)，CNN 部署与验收见 [`POI_CNN.md`](./POI_CNN.md)。

## 共享支持代码

| 文件 | 用途 |
|------|------|
| [`tests/conftest.py`](../tests/conftest.py) | pytest fixture、offscreen 环境、隔离运行数据 |
| [`tests/support/feature_fakes.py`](../tests/support/feature_fakes.py) | capture / region / HUD 等 fake 服务 |
| [`tests/support/platform.py`](../tests/support/platform.py) | 共享 `FakeBackend` |
| [`tests/support/qt.py`](../tests/support/qt.py) | `process_events()` |
| [`tests/support/paths.py`](../tests/support/paths.py) | 仓库路径与地图截图路径，避免目录移动影响路径推导 |

## 运行测试

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture -q

# 按类别运行
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture tests/core -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture tests/plugins/map_detect -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture tests/ui tests/platforms -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture tests/legacy -q

.venv/bin/ruff check src tests scripts tools
.venv/bin/ruff format --check src tests scripts tools
git diff --check
```

`-p no:capture` 禁用 pytest 输出捕获插件，测试本身不依赖此参数。

多屏测试是合成数据回归，不能替代操作系统和显卡后端实测。实机验证使用 `scripts/diagnose_capture.py`，步骤与边界见 [`MULTISCREEN_CAPTURE.md`](./MULTISCREEN_CAPTURE.md)。

## 约束与新增测试

- Qt 测试在 `QT_QPA_PLATFORM=offscreen` 下运行。
- 每个测试使用临时运行数据目录，不访问用户实际配置。
- 复杂 fixture 必须注册所需服务，避免定时器回调 `require()` 失败导致进程 abort。
- 核心逻辑、插件、UI 与平台行为分别放入对应分类；新的地图测试放入 `tests/plugins/map_detect/`。
- 共用 fake 和工具放入 `tests/support/`；只供单个模块使用的 fixture 留在该模块。
- 核心逻辑必须有单元测试；插件需覆盖加载、激活、事件处理、停用与资源释放。
- 提交前运行 pytest、Ruff 检查、格式检查及 `git diff --check`。
