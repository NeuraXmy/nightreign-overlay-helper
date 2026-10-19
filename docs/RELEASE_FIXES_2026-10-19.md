# 发布审计修复记录

对应 [2026-10-19 发布审计](RELEASE_AUDIT_2026-10-19.md)。原报告保留为检查时快照，本页记录修复后的行为。按报告顺序处理 18 项；A14、A16、A18、A19 按原报告的“无需修复”评论保留现状。

| ID | 修复后行为 | 验证入口 |
| --- | --- | --- |
| A01 | 安全声明断言与正式文案同步，继续检查截图、内存访问声明和官方联机说明 | `tests/ui/test_faq.py` |
| A02 | `uv.lock` 纳入源码交付，构建 `uv sync --locked`；统一使用 PyPI，CI 缓存包含锁文件 | `uv lock --check`、`build.bat` |
| A03 | 打包前独立执行 pytest、Ruff lint／format、资源推理和插件发现门禁；打包清单补充两个血条模型 | `.github/workflows/build-windows.yml`、`scripts/check_runtime_resources.py` |
| A04 | 数值入口拒绝非有限和无法表示的数字；启动回退默认值，导入和运行时设置拒绝非法输入 | `tests/core/test_config.py` |
| A05 | 目录创建、备份和临时文件清理均处理 I/O 异常；保存失败保留 dirty、发出可见提示，后续 flush 可重试 | `tests/core/test_config.py`、`app.py` |
| A06 | 区域坐标、尺寸和右／下边界受 Qt 有符号 32 位范围约束，尺寸必须为正，负坐标仍合法 | `tests/plugins/test_infrastructure_plugins.py` |
| A07 | 监听失败拒绝主实例资格；以 QLockFile 串行化陈旧地址清理和监听，防止启动竞态 | `tests/core/test_single_instance.py` |
| A08 | 构造或 on_load 失败时释放 context 服务、订阅和 cleanup | `tests/core/test_plugin_manager.py` |
| A09 | 加载失败后重新启用会重建 context／插件并重试初始化 | `tests/core/test_plugin_manager.py` |
| A10 | 输入初始化前登记清理，pygame 初始化前记录句柄；单个 listener.stop 失败不阻断其余清理；激活重试恢复 HotkeyApi | `tests/plugins/test_infrastructure_plugins.py` |
| A11 | 图片任务总数上限 8，快照总量上限 64 MiB；关闭等待最多 1 秒，取消未开始任务；提交与关闭互斥 | `tests/core/test_debug_images.py`、[存储约定](DEBUG_IMAGES.md) |
| A12 | 重置停止延迟定时器、递增 generation、清空计时；回调校验当前区域 | `tests/plugins/test_art_timer.py`、`test_audio_notifications.py` |
| A13 | 每个 hat 事件先释放失效方向，再按下当前方向，保留斜向释放约定 | `tests/plugins/test_infrastructure_plugins.py` |
| A15 | 每个测试进入和退出均清理数据目录缓存；进入时先切换环境变量 | `tests/conftest.py`、`tests/core/test_config.py` |
| A17 | 相同截图错误至多每分钟输出一次堆栈；恢复输出一条日志；仍按配置频率重试 | `tests/plugins/test_capture_backends.py` |
| A20 | 重建两份血条说明并核对当前实现；docs UTF-8 测试拒绝替换字符和连续问号段 | `tests/core/test_i18n.py` |
| A21 | 清理旧悬浮窗测试入口、修正数据目录变量、关闭行为和即时主题约束；同步相关知识卡片 | `README.md`、`L2_CORE.md`、`L4_PLUGIN_SYSTEM.md`、`L9_AI_CHECKLIST.md` |
| A22 | tag 构建按 PEP 440 规范化后比较内部版本；手动构建标记 manual-dev | `scripts/validate_release_version.py`、`tests/core/test_release_version.py` |

## 验证范围

本轮本地验证环境为 macOS、Python 3.12，使用锁文件安装依赖，Qt 采用 offscreen。

- 完整 pytest：**1031 passed、18 warnings，128.37 秒**；新增修复记录加入后，文档／国际化检查另行通过。
- `ruff check .`、`ruff format --check .`、`git diff --check`：通过。
- `uv lock --check --offline`：通过。
- `scripts/check_runtime_resources.py`：通过。
- `scripts/validate_release_version.py v1.0.0-dev.2` 及等价／不匹配版本回归：通过。

资源冒烟验证实际加载三个 ONNX 模型并完成一次推理，检查全部 11 个内置插件发现与 on_load；不激活物理输入或连接游戏。

Windows x64 的 Python 3.13 锁定打包由 CI 执行。当前本地验证不能替代分发 EXE、Steam/ETW、UAC、截图 DLL、HDR、多屏和真实输入设备验收。

调试图片关闭的时间预算约束调用线程；已开始的底层磁盘写入无法强制中断，会在后台完成。Python 解释器退出仍可能等待这一个运行中的写入。队列总量与快照内存已有明确上限。

原报告 A18 的算法警告及验收阈值继续保留；本轮未调整血条算法。
