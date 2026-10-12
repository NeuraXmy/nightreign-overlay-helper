# Nightreign Overlay Helper

《艾尔登法环 黑夜君临》悬浮窗辅助工具的重写版本。目前包含应用底座与一个独立的悬浮窗测试插件；旧版业务功能尚未迁移。

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

## 许可证

[AGPL-3.0-only](LICENSE)
