# 测试策略

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
├── support/                 # 共享 fake、Qt 工具、仓库/样本路径
└── data/                    # Git 跟踪的测试数据，按功能分目录（地图、血条、倒地、异常量表等）
```

每个测试分类都是 Python 包。共享工具通过 `tests.support.*` 导入；测试之间不互相导入，也不导入 `conftest.py` 中的普通函数。全局 fixture 由 pytest 自动发现。截图、录像、标注等静态测试数据统一放在 `tests/data/<功能>/` 下，不另建 `tests/fixtures/` 数据目录。

## 分类与覆盖

血条检测的拒识率验收统一为：不超过 20% 正常通过，超过 20% 且不超过 50% 时通过并在 pytest 警告摘要中报告，超过 50% 时失败。连续回放按每种采样间隔统计；生产录像冷启动按所有窗口的拒识次数／检测次数汇总，灰血独立冷启动兼容测试仍按每个窗口统计。最长连续拒识不超过 2 秒正常通过，超过 2 秒且不超过 5 秒时警告通过，超过 5 秒时失败；适用于连续回放和已有的冷启动连续拒识检查。零错误与首次输出时间仍分别检查。阈值由 `tests/support/hp_assertions.py` 统一实现。

四段生产血条录像的日常回归使用 [`test_hp_production_videos.py`](../../../tests/plugins/test_hp_production_videos.py) 的简化版：每个 GT 段起点及最后一段尾部抽取 3 秒窗口，每窗口只读取 12 个真实录像帧（0.25 秒采样），各窗口使用独立生产检测器。覆盖两段灰血录像的容量变化、复杂粉色／黄色背景、零错误、至少 50% 有效输出和首次输出小于 2.5 秒；四段合计目标低于 10 秒。它不代替整段录像的连续拒识和多采样率验收。耗时用 `--durations=10` 查看，不使用依赖机器负载的硬时间断言。

原有三种采样率的全录像回放、每个可用整秒起点的独立五秒冷启动及原验收阈值，完整保留在 [`benchmark/benchmark_hp_production.py`](../../../benchmark/benchmark_hp_production.py)。**只有血条检测部分发生修改时才运行该 benchmark**（包括检测算法、材质模型／权重、检测参数、标定／裁剪几何以及相关样本或标注）；更新检查、翻译等无关修改不运行。普通 `pytest` 只发现 `tests/`；构建和发布 CI 显式运行 `tests -m "not benchmark"`，不执行此 benchmark。命令如下：

```bash
# 日常四段录像简化回归；查看合计耗时
QT_QPA_PLATFORM=offscreen uv run pytest tests/plugins/test_hp_production_videos.py -q --durations=10

# 仅血条检测相关修改：原完整验收（保留拒识率、连续拒识、冷启动断言）
QT_QPA_PLATFORM=offscreen uv run pytest benchmark/benchmark_hp_production.py -m benchmark -q --durations=10
```

国际化测试保留核心 UI 的全语言完整性检查。插件 UI 只要求 `zh_CN.yaml` 完整且非空，检查插件名称、描述与源码字面量／条件分支引用；动态词条由插件 UI 测试覆盖。其他语言可缺少 UI 词条，已有词条仍检查中文基准、字符串类型和格式占位符。地图名称表单独检查：每个正式语言的 `<语言>-names.csv` 必须覆盖 `zh_CN-names.csv` 的全部 ID，且名称非空、ID 不重复；直接读取 CSV，不能让运行时中文回退掩盖缺项。

| 目录 | 测试模块 | 覆盖内容 |
|------|----------|----------|
| `core/` | `test_config.py`、`test_events_services.py`、`test_i18n.py`、`test_plugin_manager.py` | 配置、事件/服务、翻译、插件依赖与生命周期 |
| `core/`、`plugins/` | `test_images.py`、`test_debug_images.py`、`test_image_resources.py`、`test_unicode_installation.py` | Unicode 路径下图片/模板读写、异步诊断图片与元数据、损坏资源诊断，以及复制安装目录后的插件、字体、ONNX 和截图 DLL 加载 |
| `plugins/` | `test_capture_backends.py`、`test_infrastructure_plugins.py`、`test_region_preview.py` | 截图后端、输入/HUD/区域服务、区域预览 |
| `plugins/` | `test_capture_multiscreen.py`、`test_capture_diagnostic.py` | Windows/macOS 四方向副屏、负坐标、混合 DPI、DLL 客户区、标定/预览/地图叠加坐标一致性 |
| `plugins/` | `test_debuff_timer.py`、`test_debuff_detector.py` | 异常量表固定周期、10 层上限、HUD、生命周期、标定与无损截图增强 |
| `plugins/` | `test_art_timer.py`、`test_day_timer.py`、`test_rain_timer.py` | 计时插件识别、状态机、快捷键、HUD |
| `plugins/` | `test_hp_marker.py`、`test_p2p_latency.py` | 血条标记、P2P 服务与窗口布局 |
| `plugins/` | `test_hp_detection_accuracy.py`、`test_hp_detection_video.py` | 血条截图与增强、整段无损视频的 GT 误差、拒识比例与连续拒识时间、采样间隔及检测状态重置 |
| `plugins/` | `test_p2p_helper_path.py` | 源码、构建输出和打包组件路径解析、显式路径覆盖 |
| `plugins/map_detect/` | `test_map_detect.py`、`test_manual_catalog.py` | 地图状态机、设置、后台任务、手动筛选与候选约束 |
| `plugins/map_detect/` | `test_map_terrain.py`、`test_map_nightlord.py` | 地形与夜王标注截图回归 |
| `plugins/map_detect/` | `test_map_full_map.py` | 全图原图、颜色与清晰度增强、半透明与裁剪拒绝率、额外增强参数和无效输入 |
| `plugins/map_detect/` | `test_map_stability.py` | 地图开启／关闭稳定窗口、实际视频采样相位、渐变期间全图误放行、时间戳及局部动画 |
| `plugins/map_detect/` | `test_poi_cnn.py`、`test_map_localization.py` | ONNX CPU 单点/批量推理、类别约束、14 张地图 ID 验收、名称本地化 |
| `ui/` | `test_overlay.py`、`test_settings_reset.py`、`test_tray_exit.py` | 悬浮窗、设置重置、托盘与应用退出 |
| `ui/` | `test_faq.py` | FAQ Markdown、相对图片路径、语言回退、首页/关于页紧凑头图，以及页面销毁后的垃圾回收与事件循环 |
| `platforms/` | `test_overlay_activation.py` | macOS 原生非激活窗口行为 |
| `platforms/` | `test_elevation.py` | Windows 管理员权限检查、提权交接参数、取消与失败处理；通过模拟 API 避免触发真实 UAC |

通用悬浮窗和共享 HUD 的行为测试位于 `ui/test_overlay.py`，插件发现测试检查正式内置插件集合。

异常量表的背景误检、组合增强和单次检测耗时见 [2026-10-23 验证记录](debuff-detection-2026-10-23.md)。

送葬者额外绝招的偏红场景误触发、组合增强和单次检测耗时见 [2026-10-23 验证记录](undertaker-detection-2026-10-23.md)。

队友存在性、倒地与三倒的人工标注录像帧、组合增强及单次检测耗时见 [2026-10-23 验证记录](teammate-detection-2026-10-23.md)。

地图识别通过标注截图、生产部署推理和状态机测试验证。样本规则与复测命令见 [地图识别测试](map-detection.md)，CNN 部署与验收见 [POI CNN](../../features/map/poi-cnn.md)。

测试不依赖相邻旧项目或其配置文件。血条结构检测、已有截图准确率、历史状态重置和插件行为由 `plugins/test_hp_detection_accuracy.py` 与 `plugins/test_hp_marker.py` 覆盖。

FAQ 本地资源使用规范化后的 `Path` 比较，兼容 Qt 与操作系统的路径分隔符差异。HUD 子部件重新显示后的高度允许 ±2 逻辑像素偏差，以容纳 Qt 布局取整；隐藏时仍必须缩小。

## 共享支持代码

| 文件 | 用途 |
|------|------|
| [`tests/conftest.py`](../../../tests/conftest.py) | pytest fixture、offscreen 环境、隔离运行数据 |
| [`tests/support/feature_fakes.py`](../../../tests/support/feature_fakes.py) | capture / region / HUD 等 fake 服务 |
| [`tests/support/platform.py`](../../../tests/support/platform.py) | 共享 `FakeBackend` |
| [`tests/support/qt.py`](../../../tests/support/qt.py) | `process_events()`、`delete_qobjects()` |
| [`tests/support/paths.py`](../../../tests/support/paths.py) | 仓库路径与地图截图路径，避免目录移动影响路径推导 |
| [`tests/support/hp_video.py`](../../../tests/support/hp_video.py) | 血条视频逐帧评估及检测耗时统计，供视频回归测试使用 |
| [`tests/support/debuff_images.py`](../../../tests/support/debuff_images.py) | 异常量表的单项与组合图像增强，供回归测试和性能测量共用 |
| [`tests/support/undertaker_images.py`](../../../tests/support/undertaker_images.py) | 送葬者图标的原有及组合增强，供回归测试和性能测量共用 |
| [`tests/support/teammate_images.py`](../../../tests/support/teammate_images.py) | 队友上下槽位 GT 解析、状态检查和组合增强，供回归测试和性能测量共用 |

## 运行测试

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -X faulthandler -m pytest tests -m "not benchmark" -p no:capture -q

# 按类别运行
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture tests/core -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture tests/plugins/map_detect -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture tests/ui tests/platforms -q

.venv/bin/ruff check src tests scripts tools benchmark
.venv/bin/ruff format --check src tests scripts tools benchmark
git diff --check
```

`-p no:capture` 禁用 pytest 输出捕获插件，测试本身不依赖此参数。
macOS 上应保留此参数：部分基于 Conda Python 的环境在导入原生 `readline` 扩展时会段错误，
而 pytest 的默认捕获插件会在测试收集前导入 `readline`。禁用捕获插件可绕过这条环境问题；
标准命令已包含该参数。Windows CI 使用其原有 pytest 命令，不需要此 macOS 专用规避。
排查耗时可追加 `--durations=20`，查看最慢的测试调用、fixture setup 与 teardown；
两个 Windows workflow 默认输出该排名，避免将 fixture 中的视频评估耗时误认为断言本身耗时。

Windows 文件路径兼容性回归可将 `--basetemp` 指向仓库内含中文的临时目录，例如
`--basetemp .tmp/中文路径回归`，覆盖配置导入导出、音频、诊断 ZIP 等使用 `tmp_path` 的测试。
`test_unicode_installation.py` 另外将整个程序包复制到含中文、日文、重音字符和 emoji 的安装路径，
通过独立进程加载实际资源；它不启动截图、输入监听或 Steam/ETW。

### Qt 页面清理

测试没有运行应用主事件循环，单独调用 `deleteLater()` 后立即结束测试，不能保证 Qt 在 Python 回收页面与子控件包装对象之前完成删除。Windows / Qt 6.11 下，FAQ 页面的待处理 `PolishRequest` 事件可能在后续测试的嵌套事件循环中触发文本控件访问冲突；因此不能仅按堆栈顶部将其归因于后续悬浮窗测试。

FAQ 测试通过 `delete_qobjects(*objects)` 清理页面及相关服务：保留 Python 强引用，逐个调用 `deleteLater()`，再立即处理指定根对象的 `DeferredDelete`，确保其对象树在返回之前销毁。该辅助函数不处理其它排队回调，不能在对象自己的事件回调中使用，也不要同时传入一个父对象和它的子对象。`test_faq_teardown_survives_collection_before_next_event_loop` 主动触发垃圾回收与后续事件循环，验证页面与浏览器均已销毁。普通 UI 测试优先正确释放资源；修改全局主题的测试另见下节的进程隔离要求。

### Python 原生崩溃与全局主题测试

`Fatal Python error: Segmentation fault`、`Bus error`、`Abort trap` 或 Windows 访问冲突表示原生进程退出，不能按普通 Python 断言失败处理，也不能通过 `try/except` 捕获。Qt/PyQt、图形后端及其他原生依赖都可能触发这种退出，需要先看堆栈再定位；不能仅因进程名是 Python 就归因于 Python 版本。

2026-10-22 核对本地 macOS 的四份崩溃报告时，发现两种不同路径：

| 观察到的路径 | 诊断与处理 |
| --- | --- |
| 三份报告进入 `QMenu::event`、`QWidget::event`、`QWidget::ensurePolished`；最近一次全套回归在全局主题切换后的更新弹窗构造阶段退出，单独执行该测试可通过 | 提示测试顺序、控件生命周期或全局样式状态存在相互影响；这些堆栈尚不能确定具体哪个旧控件已失效。先核对对象清理，再隔离会修改全局样式的测试。 |
| 一份报告进入 `libqcocoa`、`NSApplication`、`_RegisterApplication` 并 `SIGABRT` | 该次进程使用了 macOS Cocoa 图形后端。无界面自动测试应在 Python 启动前显式设置 `QT_QPA_PLATFORM=offscreen`，避免依赖桌面会话。 |

Fluent Widgets 的 `setTheme()` 会遍历进程级样式注册表，刷新此前注册的控件，而全套测试共享一个 `QApplication`。只恢复浅色／深色设置不能隔离这些控件及其待处理事件。已有 [`test_release_dialog_background_follows_fluent_theme`](../../../tests/ui/test_updates.py) 因此在独立 Python 子进程中执行真实的深色→浅色→深色切换与弹窗背景断言：子进程显式使用 `offscreen`，检查退出码、保留标准输出和错误输出，并设置 30 秒超时。改为隔离后，当次默认全套回归 1139 项通过；这验证了处理方式，但不代表所有原生崩溃均已解决。

新增测试遵循以下规则：

- 在主线程创建和操作 Qt 对象；工作线程通过信号传递结果。结束测试前停止定时器，取消并等待工作线程退出，再销毁依赖对象。
- 普通 UI 测试使用共享 `qapp`，对自行创建的页面、窗口和服务使用 `try/finally` 与 `delete_qobjects()` 完成清理；`close()` 只关闭窗口，不保证销毁对象。不要盲目清空全局样式注册表或强制删除其他测试的控件。
- 新增调用 `setTheme()` 等会重设进程级 UI 状态的测试时，沿用更新弹窗测试的独立进程方式；不要只改变收集顺序或反复重跑到通过。子进程使用 `sys.executable`，避免意外切换虚拟环境，并传入 `-X faulthandler` 以便诊断。
- 在 Python 启动前显式设置 `QT_QPA_PLATFORM=offscreen`；`conftest.py` 的 `setdefault` 不会覆盖外部已有的 `cocoa` 等设置，子进程也应显式指定。需要真实桌面的平台验收应单独安排。

再次出现崩溃时，先保存完整日志，使用原环境按以下顺序缩小范围：

```bash
# 保留原生崩溃时所有 Python 线程的堆栈和最后执行的测试名
QT_QPA_PLATFORM=offscreen .venv/bin/python -X faulthandler -m pytest tests -m "not benchmark" -vv --tb=long > .tmp/pytest-native-crash.log 2>&1

# 单独执行最近出错项，并与日志中此前的 UI 测试按相同顺序组合执行
QT_QPA_PLATFORM=offscreen .venv/bin/python -X faulthandler -m pytest tests/ui/test_updates.py::test_release_dialog_background_follows_fluent_theme -vv
```

运行日志命令前创建 `.tmp/`。macOS 同时查看 `~/Library/Logs/DiagnosticReports/` 中对应时间的崩溃报告，区分 Qt 事件、Cocoa 初始化和其他原生库；分享报告前清理个人路径。记录 Python、PyQt6、Qt、Fluent Widgets 版本和实际解释器路径，使用 `uv sync --locked` 恢复匹配的依赖环境。单测通过而组合失败时继续检查前序资源释放；修复后仍需跑默认全套回归。`offscreen`、禁用 pytest 输出捕获和更换 Python 版本都不能替代 Qt 对象生命周期修复。

多屏测试是合成数据回归，不能替代操作系统和显卡后端实测。实机诊断使用 `tools/diagnose_capture.py`，步骤与边界见 [多屏截图与 DPI](../../guides/multiscreen-capture.md)。

## 约束与新增测试

- Qt 测试在 `QT_QPA_PLATFORM=offscreen` 下运行。
- 每个测试使用临时运行数据目录，不访问用户实际配置。
- 复杂 fixture 必须注册所需服务，避免定时器回调 `require()` 失败导致进程 abort。
- 核心逻辑、插件、UI 与平台行为分别放入对应分类；新的地图测试放入 `tests/plugins/map_detect/`。
- 共用 fake 和工具放入 `tests/support/`；只供单个模块使用的 fixture 留在该模块。
- 核心逻辑必须有单元测试；插件需覆盖加载、激活、事件处理、停用与资源释放。
- 提交前运行 pytest、Ruff 检查、格式检查及 `git diff --check`。

[返回开发维护](../README.md)
