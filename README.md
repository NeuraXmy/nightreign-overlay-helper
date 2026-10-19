# Nightreign Overlay Helper

《艾尔登法环 黑夜君临》桌面悬浮窗辅助工具，提供缩圈、雨中冒险与绝招计时、地图信息、血量阈值标记和联机状态。

## 运行环境

- Python 3.11+
- Windows（主要支持平台）或 macOS（开发调试）

## 安装与运行

使用 `uv`：

```bash
uv sync --locked --dev
uv run python main.py
```

或使用标准 `venv`：

```bash
python -m venv .venv
.venv/bin/python -m pip install -e . pytest ruff
.venv/bin/python main.py
```

Windows 下将命令中的 `.venv/bin/python` 替换为 `.venv\Scripts\python.exe`。

程序也可通过安装后的命令启动：

```bash
nightreign-overlay-helper
```

## 验证

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

启动后可在各功能设置页调整悬浮窗，在通用设置中调整显示方式、透明度与鼠标穿透。macOS 无法检测游戏前台窗口；如果透明悬浮窗显示异常，请在「设置 → 悬浮窗显示方式」中选择「普通窗口」。

## 项目文档

[文档总索引](docs/INDEX.md)按项目概览、架构、功能、使用指南和开发维护组织资料：

- 了解项目：[项目概览](docs/overview.md)与[架构文档](docs/architecture/README.md)。
- 查阅功能：[功能文档](docs/features/README.md)与应用内教程。
- 排查问题：[使用与诊断指南](docs/guides/README.md)。
- 开发与发布：[开发约定](docs/development/contributing.md)、[测试策略](docs/development/testing/README.md)、[Windows 构建与发布](docs/development/releases/README.md)。

## Windows 发布版

下载并解压完整发布 ZIP 后，运行 `nightreign-overlay-helper.exe`。须保留同级的 `_internal/`、`bin/` 与 `third-party/`，移动或分发时保留整个文件夹。发布版自带 Python 与 .NET 运行库，用户无需单独安装。

程序在 Windows 请求管理员权限，联机状态需要已登录的 Steam；ETW 不可用时仍可查询 Steam 连接。设置、日志与缓存写入用户数据目录，问题反馈可从“关于”页导出诊断 ZIP。

源码构建需 Windows x64、uv 与 .NET 8 SDK，执行 `build.bat`；完整步骤、CI 下载方式和验收边界见[发布指南](docs/development/releases/README.md)。

## 许可证

[AGPL-3.0-only](LICENSE)
