# 联机状态

## 文件

- [`src/nightreign_overlay/plugins/p2p_latency/plugin.py`](../../src/nightreign_overlay/plugins/p2p_latency/plugin.py)
- [`src/nightreign_overlay/plugins/p2p_latency/service.py`](../../src/nightreign_overlay/plugins/p2p_latency/service.py)
- [`src/nightreign_overlay/plugins/p2p_latency/overlay.py`](../../src/nightreign_overlay/plugins/p2p_latency/overlay.py)
- [`src/nightreign_overlay/plugins/p2p_latency/models.py`](../../src/nightreign_overlay/plugins/p2p_latency/models.py)
- [`src/nightreign_overlay/plugins/p2p_latency/mock_helper.py`](../../src/nightreign_overlay/plugins/p2p_latency/mock_helper.py)

## 职责

显示 Steam 联机队友、Ping、稳定度。

## 依赖

无截图/HUD 依赖；独立 `P2POverlay`。

## 架构

- Windows：启动原生 `NightreignP2PHelper` 子进程，通过 JSONL 协议通信。
- macOS：启动 `mock_helper.py` 模拟数据。
- `P2PService` 管理子进程、解析输出、维护状态/玩家列表。
- `P2POverlay` 显示状态与玩家列表。

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

执行 `dotnet run --project native/NightreignP2PHelper.Tests -c Release` 可运行原生队友发现回归测试。
测试链接实际的队友读取代码，使用内存中的 Steam／ETW 响应，覆盖受邀好友缺失同服务器记录、
过期历史记录、无效会话过滤、会话保持与断开、ETW 暂无指标等场景，无需运行 Steam 或游戏。
构建和发布 workflow 均执行这些检查。

macOS 开发运行自动使用独立 Python 模拟子进程，无需 .NET、Steam 或管理员权限。约 32 秒循环演示等待、
未知指标、延迟分色和队友更换；设置页明确标明模拟数据。此模式用于验证设置、悬浮窗和进程生命周期，
不代表真实网络测量。主界面打开时可拖动联机悬浮窗，关闭后锁定；大小、透明度、位置和 Ping 分色阈值可持久化。

旧接口的稳定度由最近 RTT 样本的抖动计算，并非丢包率；新接口使用 Steam 提供的本地连接质量。
[返回功能索引](README.md)
