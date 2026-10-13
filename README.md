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

## Windows 文件夹构建

在 Windows x64 上安装 `uv` 与 .NET 8 SDK，并确保它们已加入 `PATH`，然后运行项目根目录的：

```bat
build.bat
```

脚本从自身所在目录执行，使用 Python 3.13（由 `uv` 管理），同步 `build` 依赖组，
构建 Steam/ETW 辅助程序，再通过 `nightreign-overlay-helper.spec` 构建主程序。
首次构建需要联网下载 Python、Python 依赖与 NuGet 包。自动化环境可设置 `CI=1` 跳过结束时的暂停。

输出为完整文件夹，而非单个 EXE：

```text
dist/nightreign-overlay-helper/
├── nightreign-overlay-helper.exe
├── _internal/                 # Python、Qt、第三方库、核心与插件资源、截图 DLL
├── bin/                       # 联机辅助 EXE、.NET 运行库、Steam/ETW 依赖
├── third-party/               # 联机组件的第三方声明与许可证
├── LICENSE
└── README.md
```

运行 `nightreign-overlay-helper.exe` 即可；发布、移动或压缩分发时须保留整个文件夹，
不能只复制 EXE。主程序采用 PyInstaller `onedir`，联机辅助程序也采用自包含多文件发布，
启动时不需要将内嵌运行库解压到临时目录，用户无需安装 Python 或 .NET。
设置、日志与缓存仍写入用户数据目录，不写入 `_internal`。

截图 DLL 已从旧版迁移至 `src/nightreign_overlay/plugins/capture/native/`；
构建不依赖相邻的旧版项目。spec 自动收集各插件的翻译、教程、图片、模板、CSV 与字体，
并保留旧版 Qt VC 运行库收集和 OpenCV/Qt ICU 冲突过滤。
Windows EXE 必须在 Windows 上构建；macOS 开发环境不能直接生成该产物。

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
单独构建脚本默认沿用旧版单文件发布；添加 `-NoSingleFile` 可改为多文件发布，
完整的 `build.bat` 已使用该选项，并复制整个辅助程序目录。

macOS 开发运行自动使用独立 Python 模拟子进程，无需 .NET、Steam 或管理员权限。约 32 秒循环演示等待、
未知指标、延迟分色和队友更换；设置页明确标明模拟数据。此模式用于验证设置、悬浮窗和进程生命周期，
不代表真实网络测量。主界面打开时可拖动联机悬浮窗，关闭后锁定；大小、透明度、位置和 Ping 分色阈值可持久化。

旧接口的稳定度由最近 RTT 样本的抖动计算，并非丢包率；新接口使用 Steam 提供的本地连接质量。

## 许可证

[AGPL-3.0-only](LICENSE)
