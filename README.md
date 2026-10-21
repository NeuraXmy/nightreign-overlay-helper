<div align="center">
  <h1>黑夜君临悬浮助手</h1>
  <p>《艾尔登法环 黑夜君临》桌面悬浮窗工具，提供计时、地图信息、血量参考线与联机状态。</p>
  <p>
    <a href="https://github.com/NeuraXmy/nightreign-overlay-helper/releases"><img alt="下载数" src="https://img.shields.io/github/downloads/NeuraXmy/nightreign-overlay-helper/total?logo=github&style=flat-square&color=1E9BFA"></a>
    <a href="https://github.com/NeuraXmy/nightreign-overlay-helper/releases"><img alt="Release" src="https://img.shields.io/github/v/release/NeuraXmy/nightreign-overlay-helper?style=flat-square&color=1E9BFA"></a>
  </p>
  <p><a href="https://github.com/NeuraXmy/nightreign-overlay-helper/releases">下载 Windows 版</a> · <a href="README_en.md">English</a></p>
</div>

项目使用 **GPT-6.1-Sol** 辅助开发与翻译。

当前版本在 [`main`](https://github.com/NeuraXmy/nightreign-overlay-helper/tree/main) 分支开发（原 `rewrite` 分支）。旧版主线已迁移至 [`legacy`](https://github.com/NeuraXmy/nightreign-overlay-helper/tree/legacy)（原 `main`），旧版开发分支已迁移至 [`legacy-dev`](https://github.com/NeuraXmy/nightreign-overlay-helper/tree/legacy-dev)（原 `dev`）。维护旧版的 fork 请从 `legacy` 或 `legacy-dev` 同步；`main` 现在对应新版代码。

## 功能

- **缩圈计时**：识别每天开始时的 DAY I / DAY II / DAY III 图标，自动在悬浮窗显示缩圈倒计时，也可用快捷键手动计时。
- **雨中冒险计时**：定时截图检测血条颜色，进入雨中时倒计时，提示大幅受伤前的剩余时间；血条恢复正常颜色后自动停止。
- **绝招计时**：按下游戏内绝招按键且绝招图标亮起时，显示绝招生效时间倒计时。支持女爵、隐士、执行者、复仇者和学者。
- **语音播报**：内置 10 条默认语音，每项独立开关、音量、试听及自定义文件。两次缩圈默认提前 30 秒、绝招结束提前 3 秒；雨中冒险的开始、剩余 30 秒预警和结束分别设置。详见 [计时与语音](docs/features/timers.md)。
- **地图信息**：识别特殊地形、夜王头像和据点类型，筛选地图种子并显示详细据点信息。支持所有地图（含 DLC）及隐藏夜王、隐藏地图详细信息事件，部分情况需手动筛选。
- **血量阈值标记**：定时截图检测血条长度，显示“血量不满时……”和“血量较低时……”词条的触发血量参考线。
- **联机状态**：显示 Steam 联机队友的昵称、Ping 和连接稳定度；可开关免 API Key 的公开游戏时长，点击名字进入 Steam 内置主页。
- **赛后点赞**：独立页面与限时窗口，名字打开主页，点赞按钮发送自定义留言；保留七天防重复与不确定结果保护。详见 [队友功能](docs/features/steam-social.md)。
- **自动屏蔽与恢复**：联机状态页开关，默认关闭；有效延迟出现后处理非好友，离队后恢复，保留异常恢复记录。详见 [通信恢复](docs/features/steam-recovery.md)。

## 使用方法

1. 下载并完整解压 [Windows 发布 ZIP](https://github.com/NeuraXmy/nightreign-overlay-helper/releases)。保留 EXE 同级的 `_internal/`、`bin/`、`third-party/` 等目录，不要单独移动 EXE。发布版自带 Python 和 .NET 运行库，无需另行安装。
2. 双击 `nightreign-overlay-helper.exe`，按提示授予管理员权限。使用联机状态功能前，请先登录 Steam。
3. 将游戏设为窗口化或无边框窗口化。Windows 下未手动标定的区域自动适配 16:9 游戏窗口；手动标定后优先使用手动数据。按各功能页面的“教程”选择游戏语言、配置快捷键，必要时手动调整区域。
4. 右键悬浮窗或系统托盘图标可打开主界面。关闭主界面会隐藏到托盘；完全退出请选择右键菜单中的“退出程序”。

主界面打开时可调整悬浮窗位置；显示方式、透明度等可在通用设置中调整。

### 识别与问题反馈

- 识别异常时，先检查标定区域是否准确、是否被其他窗口遮挡。
- 自动区域跟随 16:9 游戏窗口的位置和尺寸；手动区域在更换显示器、分辨率、缩放或窗口位置后需检查并重新标定。支持范围见[自动识别区域](docs/features/automatic-regions.md)。
- 反馈问题时，可从“关于 → 问题反馈”导出诊断 ZIP。

## 从源码运行

### 运行环境

- Python 3.11 及以上，主要支持 Windows。
- macOS 仅用于开发调试，联机状态显示模拟数据，无法检测游戏前台窗口。
- macOS 截图需要屏幕录制权限；透明悬浮窗显示异常时，可在通用设置中选择“普通窗口”。

### 安装与启动

以下命令均在仓库根目录执行。推荐用 `uv` 按 `uv.lock` 安装依赖：

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

安装后，也可在已激活的虚拟环境中运行 `nightreign-overlay-helper` 启动。Windows 源码运行联机状态功能前，需单独构建辅助程序，详见[联机状态文档](docs/features/p2p.md)。

### 验证

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

### Windows 构建

在 Windows x64 上安装 `uv` 和 .NET 8 SDK，然后运行 `build.bat`。脚本使用 Python 3.13 和锁定依赖生成完整发布文件夹。

构建流程、GitHub Actions ZIP 下载方式及发布验收要求见[发布指南](docs/development/releases/README.md)。

## 项目文档

[文档总索引](docs/INDEX.md)汇总了项目概览、架构、功能、使用指南和开发维护资料：

- 了解项目：[项目概览](docs/overview.md)、[架构文档](docs/architecture/README.md)。
- 查阅功能：[功能文档](docs/features/README.md)、应用内教程。
- 排查问题：[使用与诊断指南](docs/guides/README.md)。
- 开发与发布：[开发约定](docs/development/contributing.md)、[测试策略](docs/development/testing/README.md)、[Windows 构建与发布](docs/development/releases/README.md)。

## 安全性声明

本工具是独立程序，并非游戏 Mod 或插件。识别功能主要依靠游戏截图和图像分析，不读写游戏进程内存，不修改游戏数据或文件，不注入代码、不改变游戏运行逻辑；读取Steam P2P网络包仅用于延迟测量，不截获或修改游戏信息。按目前的工作方式，本工具通常不会触发反作弊检测，可在官方联机模式下正常使用。但任何第三方软件都存在潜在风险，无法保证始终不被反作弊系统判定为异常；请自行评估并承担使用风险。

## 致谢

- [Fuwish](https://github.com/Fuwishx)：地图解包数据支持。
- [雀煊](https://space.bilibili.com/391379672)：大空洞水晶布局分享。
- [SteamP2PInfo](https://github.com/tremwil/SteamP2PInfo)：P2P 连接查询与 ETW 延迟测量思路。
- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/)：Fluent Design 风格界面组件库。

## 许可证

本项目采用 [AGPL-3.0-only](LICENSE)，允许依许可证使用、修改和再分发（包括商业使用），不提供任何担保。

第三方组件保留各自许可：SteamP2PInfo 为 MIT，PyQt6-Fluent-Widgets 和 PyQt6 为 GPLv3。完整文本与说明见[第三方声明](src/nightreign_overlay/resources/licenses/THIRD-PARTY-NOTICES.md)及[对应源码获取与构建说明](src/nightreign_overlay/resources/licenses/SOURCE.md)。

Windows 程序包附带 `licenses/`、`third-party/` 和 `SOURCE.md`；对应源码单独提供在同一 Release 的 `<版本>-sources.zip` 附件中。分发时保留完整程序文件夹，并提供对应源码下载入口。许可文本也可在“关于 → 许可证与源码”中离线查看。
