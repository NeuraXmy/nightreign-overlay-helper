# 联机状态

## 文件

- [`src/nightreign_overlay/plugins/p2p_latency/plugin.py`](../../src/nightreign_overlay/plugins/p2p_latency/plugin.py)
- [`src/nightreign_overlay/plugins/p2p_latency/service.py`](../../src/nightreign_overlay/plugins/p2p_latency/service.py)
- [`src/nightreign_overlay/plugins/p2p_latency/overlay.py`](../../src/nightreign_overlay/plugins/p2p_latency/overlay.py)
- [`src/nightreign_overlay/plugins/p2p_latency/models.py`](../../src/nightreign_overlay/plugins/p2p_latency/models.py)
- [`src/nightreign_overlay/plugins/p2p_latency/mock_helper.py`](../../src/nightreign_overlay/plugins/p2p_latency/mock_helper.py)

## 职责

显示 Steam 联机队友、Ping、稳定度和可开关的免 API Key 游戏时长。名字可点击打开 Steam 内置主页；独立的赛后点赞页面与窗口见 [队友功能](steam-social.md)。

设置页提供默认关闭的「显示玩家真实Steam名」开关，通过临时屏蔽非好友队友的 Steam 通信，在游戏中显示其 Steam 名字。离队后自动恢复，处理状态在页面底部显示，细节见 [通信恢复说明](steam-recovery.md)。此功能不依赖 DAY1 或 HUD 识别。

## 依赖

无截图/HUD 依赖；独立 `P2POverlay`。

## 架构

- Windows：启动原生 `NightreignP2PHelper` 子进程，通过 JSONL 协议通信。
- macOS：启动 `mock_helper.py` 模拟数据。
- `P2PService` 管理子进程、解析输出、维护状态/玩家列表。
- `P2POverlay` 显示状态与玩家列表。
- `PlaytimeService` 异步读取公开主页；`PeerSnapshot` 事件发布每个真实有效快照（包含名单未变化的情况），供赛后离队确认使用。辅助进程清理时产生的空列表不是新快照。
- 新版原生快照携带当前 Steam 账号和逐人好友关系。只有来自原生组件的有效账号才能授权屏蔽；注册表兜底账号、缺失/未知关系或旧辅助程序的名单只能用于显示。
- 隐藏基础插件 `steam_recovery` 负责持久恢复；停用联机状态会撤销新屏蔽并请求恢复，不停止独立恢复任务。

Windows 主程序默认请求管理员权限，详见 [启动流程](../architecture/startup.md)。联机插件激活时再次检查权限；无权限则在创建悬浮窗和辅助进程之前抛出 `PermissionError`，由插件管理器标记启动失败，设置页显示需要管理员权限。

ETW 权限以创建独立内核跟踪会话的实际结果为准，不使用 `TraceEventSession.IsElevated()` 预检，避免辅助进程权限探测误报。ETW 返回访问拒绝时，Steam 队友信息继续显示，悬浮窗同时提示需要管理员权限；其他 ETW 初始化错误也会显示在悬浮窗中。

队友候选取自 Steam 好友、同服务器用户和一起玩过的用户列表，再通过当前 App 的 P2P 会话状态确认连接。
不以历史记录的时间或最后游戏过滤候选：受邀好友可能没有同服务器记录，一起玩过的记录也可能延迟更新。
候选列表中的离线好友、历史玩家及连接错误不会直接作为队友显示。ETW 启动成功仅代表跟踪会话已启动，不代表已发现队友。

组件路径优先使用 `NIGHTREIGN_P2P_HELPER_PATH` 覆盖。打包运行仅使用 EXE 同级 `bin/NightreignP2PHelper.exe`。源码运行按顺序查找仓库内 `bin/`、`build/p2p/bin/`、原生项目 Debug 输出、Release 的 `publish/` 及 Release 输出目录；原生输出目标为 `net8.0-windows/win-x64`。查找与启动工作目录无关。若尚未构建，执行 `powershell -ExecutionPolicy Bypass -File scripts/build_p2p_helper.ps1`，生成组件及依赖；无需为了源码调试先打包整个应用。

## 必须保持的约束

- 联机检测不受截图门控影响；但悬浮窗仍受显示门控约束。
- macOS 明确显示为模拟数据，不伪装真实 ETW。
- ETW 只在独立会话创建被访问拒绝时报告管理员权限不足；Steam 连接查询不依赖 ETW 是否启动成功。

## 辅助程序构建与调试

Windows 使用独立 Steam／ETW 辅助程序。开发环境需要 .NET 8 SDK，执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_p2p_helper.ps1
```

脚本将自包含辅助程序发布到仓库 `bin`，并检查 `NightreignP2PHelper.exe`、
`amd64/KernelTraceControl.dll` 和 `amd64/msdia140.dll`。Steam 必须已登录，ETW 延迟测量需要管理员权限；
ETW 不可用时仍会查询 Steam 连接。发布版无需另行安装 .NET。

打包主程序时，须把整个 `bin` 放到主程序 EXE 同级目录，同时带上脚本生成的 `third-party` 许可目录。
也可用 `-OutputDirectory <发布目录>/bin` 直接发布到对应位置。辅助程序路径支持
`NIGHTREIGN_P2P_HELPER_PATH` 环境变量覆盖。原生项目及 NuGet 锁文件位于 `native/NightreignP2PHelper`。
单独构建脚本默认使用单文件发布；添加 `-NoSingleFile` 可改为多文件发布，
完整的 `build.bat` 已使用该选项，并复制整个辅助程序目录。

源码更新涉及 `native/` 后也要重新执行构建脚本。仓库根目录的 `bin/` 优先于
`build/p2p/bin/`；只打包主程序不会更新源码运行使用的根目录组件。较早的组件可能仍能
显示 Ping，但缺少新版账号、好友关系和屏蔽命令，不能据此判断屏蔽功能可用。

构建后可运行以下真实进程启动检查：

```powershell
$env:NROH_TEST_NATIVE_HELPER = (Resolve-Path bin/NightreignP2PHelper.exe).Path
uv run pytest -q tests/native/test_helper_startup.py
Remove-Item Env:NROH_TEST_NATIVE_HELPER
```

检查会在空的隔离目录中以无控制台方式启动旧事务恢复入口及两个队友槽，验证待命状态、
有限子任务、UTF-8 留言管道及约一分钟后的空闲退出，不连接 Steam 或执行屏蔽/留言。
不支持隔离目录的旧组件会在启动前拒绝。完整 `build.bat` 在 PyInstaller 前强制执行
此检查，普通 Python 测试未指定新构建组件时跳过该项。

执行 `dotnet run --project native/NightreignP2PHelper.Tests -c Release` 可运行原生队友发现回归测试。
测试链接实际的队友读取代码，使用内存中的 Steam／ETW 响应，覆盖受邀好友缺失同服务器记录、
过期历史记录、无效会话过滤、会话保持与断开、ETW 暂无指标等场景，无需运行 Steam 或游戏。
构建和发布 workflow 均执行这些检查。

执行 `dotnet run --project native/NightreignP2PHelper.RecoveryTests -c Release` 可运行屏蔽恢复的离线事务、崩溃交接和监督进程测试。测试链接实际恢复代码并用模拟通道代替 Steam，不会操作账户；两个原生测试项目都进入 Windows 构建与发布检查。

macOS 开发运行自动使用独立 Python 模拟子进程，无需 .NET、Steam 或管理员权限。约 32 秒循环演示等待、
未知指标、延迟分色和队友更换；设置页明确标明模拟数据。此模式用于验证设置、悬浮窗和进程生命周期，
不代表真实网络测量。主界面打开时可拖动联机悬浮窗，关闭后锁定；大小、透明度、位置和 Ping 分色阈值可持久化。

旧接口的稳定度由最近 RTT 样本的抖动计算，并非丢包率；新接口使用 Steam 提供的本地连接质量。
[返回功能索引](README.md)
