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
├── support/                 # 共享 fake、Qt 工具、仓库/样本路径
└── data/map_detect/         # Git 跟踪的地图截图，位置保持稳定
```

每个测试分类都是 Python 包。共享工具通过 `tests.support.*` 导入；测试之间不互相导入，也不导入 `conftest.py` 中的普通函数。全局 fixture 由 pytest 自动发现。

## 分类与覆盖

血条检测的拒识率验收统一为：不超过 20% 正常通过，超过 20% 且不超过 50% 时通过并在 pytest 警告摘要中报告，超过 50% 时失败。连续回放按每种采样间隔统计；生产录像冷启动按所有窗口的拒识次数／检测次数汇总，灰血独立冷启动兼容测试仍按每个窗口统计。最长连续拒识不超过 2 秒正常通过，超过 2 秒且不超过 5 秒时警告通过，超过 5 秒时失败；适用于连续回放和已有的冷启动连续拒识检查。零错误与首次输出时间仍分别检查。阈值由 `tests/support/hp_assertions.py` 统一实现。

国际化测试保留核心 UI 的全语言完整性检查。插件 UI 只要求 `zh_CN.yaml` 完整且非空，检查插件名称、描述与源码字面量／条件分支引用；动态词条由插件 UI 测试覆盖。其他语言可缺少 UI 词条，已有词条仍检查中文基准、字符串类型和格式占位符。地图名称表单独检查：每个正式语言的 `<语言>-names.csv` 必须覆盖 `zh_CN-names.csv` 的全部 ID，且名称非空、ID 不重复；直接读取 CSV，不能让运行时中文回退掩盖缺项。

| 目录 | 测试模块 | 覆盖内容 |
|------|----------|----------|
| `core/` | `test_config.py`、`test_events_services.py`、`test_i18n.py`、`test_plugin_manager.py` | 配置、事件/服务、翻译、插件依赖与生命周期 |
| `core/`、`plugins/` | `test_images.py`、`test_debug_images.py`、`test_image_resources.py`、`test_unicode_installation.py` | Unicode 路径下图片/模板读写、异步诊断图片与元数据、损坏资源诊断，以及复制安装目录后的插件、字体、ONNX 和截图 DLL 加载 |
| `plugins/` | `test_capture_backends.py`、`test_infrastructure_plugins.py`、`test_region_preview.py` | 截图后端、输入/HUD/区域服务、区域预览 |
| `plugins/` | `test_capture_multiscreen.py`、`test_capture_diagnostic.py` | Windows/macOS 四方向副屏、负坐标、混合 DPI、DLL 客户区、标定/预览/地图叠加坐标一致性 |
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

早期悬浮窗调试插件及其专属生命周期测试已删除；通用悬浮窗和共享 HUD 的行为测试保留在 `ui/test_overlay.py`，插件发现测试验证正式内置插件及调试插件不再被发现。

地图旧版逐像素/评分对照测试已删除；地图识别通过标注截图、生产部署推理和状态机测试验证。样本规则与复测命令见 [`MAP_DETECT_TESTING.md`](./MAP_DETECT_TESTING.md)，CNN 部署与验收见 [`POI_CNN.md`](./POI_CNN.md)。

旧版血条外部源码逐帧对照测试已移除，测试不再依赖相邻旧项目或其配置文件。当前新版结构检测、旧版截图准确率、历史状态重置和插件行为仍由 `plugins/test_hp_detection_accuracy.py` 与 `plugins/test_hp_marker.py` 覆盖。

FAQ 本地资源使用规范化后的 `Path` 比较，兼容 Qt 与操作系统的路径分隔符差异。HUD 子部件重新显示后的高度允许 ±2 逻辑像素偏差，以容纳 Qt 布局取整；隐藏时仍必须缩小。

## 共享支持代码

| 文件 | 用途 |
|------|------|
| [`tests/conftest.py`](../tests/conftest.py) | pytest fixture、offscreen 环境、隔离运行数据 |
| [`tests/support/feature_fakes.py`](../tests/support/feature_fakes.py) | capture / region / HUD 等 fake 服务 |
| [`tests/support/platform.py`](../tests/support/platform.py) | 共享 `FakeBackend` |
| [`tests/support/qt.py`](../tests/support/qt.py) | `process_events()`、`delete_qobjects()` |
| [`tests/support/paths.py`](../tests/support/paths.py) | 仓库路径与地图截图路径，避免目录移动影响路径推导 |
| [`tests/support/hp_video.py`](../tests/support/hp_video.py) | 血条视频逐帧评估及检测耗时统计，供视频回归测试使用 |

## 运行测试

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture -q

# 按类别运行
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture tests/core -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture tests/plugins/map_detect -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture tests/ui tests/platforms -q

.venv/bin/ruff check src tests scripts tools benchmark
.venv/bin/ruff format --check src tests scripts tools benchmark
git diff --check
```

`-p no:capture` 禁用 pytest 输出捕获插件，测试本身不依赖此参数。

Windows 文件路径兼容性回归可将 `--basetemp` 指向仓库内含中文的临时目录，例如
`--basetemp .tmp/中文路径回归`，覆盖配置导入导出、音频、诊断 ZIP 等使用 `tmp_path` 的测试。
`test_unicode_installation.py` 另外将整个程序包复制到含中文、日文、重音字符和 emoji 的安装路径，
通过独立进程加载实际资源；它不启动截图、输入监听或 Steam/ETW。

### Qt 页面清理

测试没有运行应用主事件循环，单独调用 `deleteLater()` 后立即结束测试，不能保证 Qt 在 Python 回收页面与子控件包装对象之前完成删除。Windows / Qt 6.11 下，FAQ 页面的待处理 `PolishRequest` 事件可能在后续测试的嵌套事件循环中触发文本控件访问冲突；因此不能仅按堆栈顶部将其归因于后续悬浮窗测试。

FAQ 测试通过 `delete_qobjects(*objects)` 清理页面及相关服务：保留 Python 强引用，逐个调用 `deleteLater()`，再立即处理指定根对象的 `DeferredDelete`，确保其对象树在返回之前销毁。该辅助函数不处理其它排队回调，不能在对象自己的事件回调中使用，也不要同时传入一个父对象和它的子对象。`test_faq_teardown_survives_collection_before_next_event_loop` 主动触发垃圾回收与后续事件循环，验证页面与浏览器均已销毁。无需通过拆分测试进程或屏蔽系统崩溃弹窗来运行完整测试。

多屏测试是合成数据回归，不能替代操作系统和显卡后端实测。实机诊断使用 `tools/diagnose_capture.py`，步骤与边界见 [`MULTISCREEN_CAPTURE.md`](./MULTISCREEN_CAPTURE.md)。

## 约束与新增测试

- Qt 测试在 `QT_QPA_PLATFORM=offscreen` 下运行。
- 每个测试使用临时运行数据目录，不访问用户实际配置。
- 复杂 fixture 必须注册所需服务，避免定时器回调 `require()` 失败导致进程 abort。
- 核心逻辑、插件、UI 与平台行为分别放入对应分类；新的地图测试放入 `tests/plugins/map_detect/`。
- 共用 fake 和工具放入 `tests/support/`；只供单个模块使用的 fixture 留在该模块。
- 核心逻辑必须有单元测试；插件需覆盖加载、激活、事件处理、停用与资源释放。
- 提交前运行 pytest、Ruff 检查、格式检查及 `git diff --check`。
