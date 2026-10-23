# 项目概览

Nightreign Overlay Helper 是《艾尔登法环 黑夜君临》的桌面悬浮窗辅助工具。它通过截图识别、快捷键和独立联机辅助程序提供信息显示，不读取或修改游戏内存。

## 功能与范围

| 功能 | 插件 | 说明 |
| --- | --- | --- |
| 缩圈倒计时 | `day_timer` | 识别 DAY 横幅、显示分阶段倒计时 |
| 雨中冒险计时 | `rain_timer` | 通过血条颜色识别雨中状态 |
| 异常量表计时 | `debuff_timer` | 首次发现异常量表后，每 20 秒判断攻击力层数，最高 10 层 |
| 绝招倒计时 | `art_timer` | 按键后识别绝招图标并计时 |
| 地图信息 | `map_detect` | 地形、夜王与据点识别，候选、水晶布局及手动筛选 |
| 血量阈值标记 | `hp_marker` | 检测可用血条长度，绘制低／高／满血参考线 |
| 联机状态 | `p2p_latency` | 显示 Steam 队友、Ping 与连接质量 |

基础插件 `capture`、`input`、`hud`、`region`、`audio` 统一提供截图、输入、展示、标定和音频能力。业务功能通过服务契约与事件协作，各自管理生命周期和配置。

Windows 是主要发布平台。macOS 用于开发调试，前台检测、透明窗口和屏幕录制权限存在平台限制，联机状态使用明确标识的模拟数据。Linux 不是正式支持平台。自动回归不能替代真实游戏、显卡、HDR、多屏与输入设备验收。

## 技术栈与运行入口

- Python 3.11 及以上；Windows x64 发布构建使用 Python 3.13。
- PyQt6、PyQt6-Fluent-Widgets：界面与悬浮窗。
- NumPy、OpenCV、Pillow、mss：图像处理与截图；Windows 另提供 Maa 截图 DLL。
- ONNX Runtime CPU：地图 POI 与血条模型推理；训练工具不属于运行时依赖。
- pynput、pygame：全局输入；QtMultimedia：音频播放。
- pytest、Ruff、uv：回归、代码规范和锁定依赖；PyInstaller：默认文件夹打包；Nuitka：独立手动编译构建。
- .NET 8：Windows Steam／ETW 辅助程序，发布版自带运行库。

安装与运行见[项目 README](../README.md)，构建和验收见[发布指南](development/releases/README.md)。

## 代码布局

```text
src/nightreign_overlay/
├── __main__.py / app.py      # 入口与应用生命周期
├── meta.py                   # 应用常量
├── core/                     # 配置、事件、服务、路径、日志、坐标
├── platforms/                # 平台能力封装
├── plugin/                   # 插件协议、上下文与管理器
├── ui/                       # 页面、设置组件和悬浮窗底座
├── resources/                # 核心翻译、FAQ、图标
└── plugins/<plugin_id>/      # 各功能和基础能力
    ├── __init__.py           # 导出 PLUGIN
    ├── api.py                # 可选的对外服务契约
    ├── config.py             # 配置声明
    ├── plugin.py             # 生命周期实现
    ├── i18n/                 # 插件词条与名称表
    └── tutorial/             # 应用内教程及图片
```

仓库中的 `tests/` 保存回归与样本，`tools/` 保存诊断、训练工具，`benchmark/` 保存评估入口，`scripts/` 与 `.github/workflows/` 保存构建和发布检查，`native/` 保存联机辅助程序源码。

## 模块边界

UI 与业务插件通过插件系统和核心服务协作；核心模块不导入 UI 或插件实现。插件间只导入提供方的 `api.py`，通过服务查询能力，通过类型化事件广播事实。`Application` 持有应用级对象，`PluginContext` 托管插件资源；工作线程通过信号把结果交回 GUI 线程。

详细约束见[架构文档](architecture/README.md)与[开发约定](development/contributing.md)。本项目已采用上述结构，早期重写路线图与逐项迁移流水已清理；旧方案可从 Git 历史查询。

[返回文档总索引](INDEX.md)
