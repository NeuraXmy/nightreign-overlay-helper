# 黑夜君临悬浮助手

[English Version](README_en.md)

《艾尔登法环 黑夜君临》桌面悬浮窗辅助工具，提供缩圈、雨中冒险与绝招计时、地图信息、血量阈值标记和联机状态显示功能。项目使用 **GPT-6.1-Sol** 辅助开发及翻译。

## 功能

- **缩圈计时**: 通过识别游戏内每天开头的 DAY I / DAY II / DAY III 图标，自动进行缩圈倒计时并显示在悬浮窗上；也可以通过快捷键手动计时。
- **雨中冒险计时**: 定时截图并检测血条颜色，血条变为雨中颜色时开始倒计时，提示角色开始大幅受伤前的剩余时间；恢复为正常颜色时自动停止倒计时。
- **绝招倒计时**: 游戏内按下绝招按键且绝招图标亮起时，在悬浮窗上显示绝招生效时间倒计时；支持女爵、隐士、执行者、复仇者、学者。
- **地图信息**: 通过识别地图中的特殊地形、夜王头像、据点类型，筛选出地图种子并显示详细据点信息；支持包括 DLC 在内的所有地图，以及隐藏夜王、隐藏地图详细信息事件，部分情况需要手动筛选。
- **血量阈值标记**: 定时截图并检测血条长度，显示游戏中“血量不满时……”和“血量较低时……”词条触发所需的血量参考线。
- **联机状态**: 显示 Steam 联机队友的昵称、Ping 和稳定度。

## 使用方法

1. 解压完整的 Windows 发布 ZIP，保留 `nightreign-overlay-helper.exe` 同级的 `_internal/`、`bin/` 和 `third-party/` 等目录，不要单独移动 EXE。发布版自带 Python 和 .NET 运行库，无需另行安装。
2. 双击 `nightreign-overlay-helper.exe`，按 Windows 提示授予管理员权限。联机状态功能需要已登录的 Steam。
3. 在各功能页面的“教程”选项卡中完成初次设置，包括区域标定、游戏语言选择及快捷键配置。游戏请使用窗口化或无边框窗口化模式。
4. 右键悬浮窗或系统托盘图标可打开主界面。关闭主界面会隐藏到托盘；完全退出时，在右键菜单中选择“退出程序”。

主界面打开时可调整悬浮窗位置，通用设置提供显示方式、透明度等选项。截图识别异常时，先检查标定区域是否准确、是否被其他窗口遮挡；更换显示器、分辨率、缩放或游戏窗口尺寸后，请重新标定。需要反馈问题时，可从“关于 → 问题反馈”导出诊断 ZIP。

## 从源码运行

### 运行环境

- Python 3.11 及以上。
- Windows 为主要支持平台；macOS 仅用于开发调试，联机状态显示模拟数据。
- macOS 无法检测游戏前台窗口，截图需要屏幕录制权限；透明悬浮窗异常时，可在通用设置中选择“普通窗口”。

### 安装与启动

以下命令均在仓库根目录执行。推荐使用 `uv`，按照 `uv.lock` 安装依赖：

```bash
uv sync --locked --dev
uv run python main.py
```

也可以使用标准 `venv`。Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e . pytest ruff
.venv\Scripts\python.exe main.py
```

macOS：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e . pytest ruff
.venv/bin/python main.py
```

安装项目后，也可以在已激活的虚拟环境中执行 `nightreign-overlay-helper` 启动程序。Windows 源码运行联机状态功能前，需要单独构建辅助程序，详见[联机状态文档](docs/features/p2p.md)。

### 验证

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

### Windows 构建

在 Windows x64 上安装 `uv` 和 .NET 8 SDK 后，运行 `build.bat`。脚本使用 Python 3.13 和锁定依赖生成完整发布文件夹。构建流程、GitHub Actions ZIP 下载方式及发布验收要求见[发布指南](docs/development/releases/README.md)。

## 项目文档

[文档总索引](docs/INDEX.md)按项目概览、架构、功能、使用指南和开发维护组织资料：

- 了解项目：[项目概览](docs/overview.md)与[架构文档](docs/architecture/README.md)。
- 查阅功能：[功能文档](docs/features/README.md)与应用内教程。
- 排查问题：[使用与诊断指南](docs/guides/README.md)。
- 开发与发布：[开发约定](docs/development/contributing.md)、[测试策略](docs/development/testing/README.md)、[Windows 构建与发布](docs/development/releases/README.md)。

## 安全性声明

本程序并非《艾尔登法环 黑夜君临》的mod/插件，而是独立程序；识别功能主要依靠游戏画面截图和图像分析，不读写任何游戏进程内存，不修改游戏数据或文件，不会向游戏注入代码或改变游戏运行逻辑，不会截取游戏网络包；因此基本不存在反作弊风险，可以在官方联机模式下使用。

## 致谢

- [Fuwish](https://github.com/Fuwishx): 地图解包数据支持。
- [雀煊](https://space.bilibili.com/391379672): 大空洞水晶布局分享。
- [SteamP2PInfo](https://github.com/tremwil/SteamP2PInfo): P2P 连接查询与 ETW 延迟测量思路。
- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/): Fluent Design 风格界面组件库。

## 许可证

[AGPL-3.0-only](LICENSE)
