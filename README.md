# Nightreign Overlay Helper

《艾尔登法环 黑夜君临》悬浮窗辅助工具的重写版本。目前已迁移缩圈、雨中、绝招计时、地图信息、血量阈值标记和联机状态，并提供独立的悬浮窗测试插件。

## 运行环境

- Python 3.11+
- Windows（主要支持平台）或 macOS（开发调试）

## 安装与运行

使用 `uv`：

```bash
uv sync --dev
uv run python main.py
```

或使用标准 `venv`：

```bash
python -m venv .venv
.venv/bin/python -m pip install -e . pytest ruff
.venv/bin/python main.py
```

Windows 下将命令中的 `.venv/bin/python` 替换为 `.venv\\Scripts\\python.exe`。

程序也可通过安装后的命令启动：

```bash
nightreign-overlay-helper
```

## 验证

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
```

启动后可在「悬浮窗测试」页面验证拖动、缩放、透明度、鼠标穿透和普通窗口 fallback。macOS 无法检测游戏前台窗口；如果透明悬浮窗显示异常，请在「设置 → 悬浮窗显示方式」中选择「普通窗口」。

架构及后续迁移路线见 [重写计划](docs/REWRITE_PLAN.md)。

## 联机状态

Windows 使用与旧版相同的独立 Steam/ETW 辅助程序。开发环境需要 .NET 8 SDK，执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_p2p_helper.ps1
```

脚本将自包含辅助程序发布到仓库 `bin`，并检查 `NightreignP2PHelper.exe`、
`amd64/KernelTraceControl.dll` 和 `amd64/msdia140.dll`。Steam 必须已登录，ETW 延迟测量需要管理员权限；
ETW 不可用时仍会查询 Steam 连接。发布版无需另行安装 .NET。

打包主程序时，须把整个 `bin` 放到主程序 EXE 同级目录，同时带上脚本生成的 `third-party` 许可目录。
也可用 `-OutputDirectory <发布目录>/bin` 直接发布到对应位置。辅助程序路径支持
`NIGHTREIGN_P2P_HELPER_PATH` 环境变量覆盖。原生项目及 NuGet 锁文件位于 `native/NightreignP2PHelper`。

macOS 开发运行自动使用独立 Python 模拟子进程，无需 .NET、Steam 或管理员权限。约 32 秒循环演示等待、
未知指标、延迟分色和队友更换；设置页明确标明模拟数据。此模式用于验证设置、悬浮窗和进程生命周期，
不代表真实网络测量。主界面打开时可拖动联机悬浮窗，关闭后锁定；大小、透明度、位置和 Ping 分色阈值可持久化。

旧接口的稳定度由最近 RTT 样本的抖动计算，并非丢包率；新接口使用 Steam 提供的本地连接质量。

## 许可证

[AGPL-3.0-only](LICENSE)
