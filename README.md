# Nightreign Overlay Helper

[中文README](#黑夜君临悬浮助手)

Nightreign Overlay Helper is a utility program developed with PyQt6, designed to display various useful information and features while playing the game, **currently supporting only the Chinese language**.

## Features

- Displays countdowns for night rain circle shrinking and fast damage of night rain, triggered by hotkeys or automatic detection.
- Map recognition and floating map information.
- Displays health percentage markers corresponding to "trigger when health is low" and "trigger when health is full" entries.
- Displays countdowns for art buffs of certain characters.
- Displays Nightreign teammate Steam names, ping, and connection stability in a separate overlay.

## Build Instructions

#### Prerequisites
- Windows 7, 8, 10, or 11
- Python 3.13
- .NET 8 SDK (build only; release packages include a self-contained helper)

#### Steps

1. Clone the repository and navigate to the project directory.

2. Build the executable using build script:

    ```bash
    .\build.bat
    ```

    You can find the built executable in the `dist/nightreign-overlay-helper` directory.


## Usage
Double-click `nightreign-overlay-helper.exe` to run the program. Right-click the overlay window or the taskbar icon to open the menu and access the settings window. Refer to the help in the settings UI for configuration guidance.

## Safety
The program recognizes game information through screenshots and reads local Steam connection metadata. It does not modify game data, read/write game memory, inject code, or hook the game/Steam process. ETW events are processed in memory without writing ETL files or displaying/logging peer IP addresses. No third-party tool can guarantee zero anti-cheat risk.

## Acknowledgements

- All image resources used in this program are copyrighted by their respective owners.
- Thanks to [Fuwish](https://github.com/Fuwishx) for map data support.
- Thanks to [雀煊](https://space.bilibili.com/391379672) for sharing the Great Hollow crystal layout.
- P2P connection-query and ETW latency concepts are adapted from [SteamP2PInfo](https://github.com/tremwil/SteamP2PInfo), licensed under MIT.

---

# 黑夜君临悬浮助手

[English README](#Nightreign-Overlay-Helper)

基于PyQt6开发的用于在游戏中显示各种实用信息和功能的辅助程序，目前界面仅支持中文语言。

## 功能

- 显示缩圈和雨中冒险倒计时，支持快捷键触发或自动检测。
- 地图识别与地图信息悬浮。
- 显示“血量较低触发”与“满血时触发”的词条对应百分比血量位置标记。
- 显示部分角色的绝招buff倒计时。
- 通过独立悬浮窗显示《黑夜君临》队友的 Steam 昵称、Ping 与连接稳定度。

## 构建

#### 环境要求

- Windows 7、8、10 或 11
- Python 3.13
- .NET 8 SDK（仅构建需要，发行包中的 Helper 已自包含运行环境）

#### 构建步骤

1. 克隆代码库并进入项目目录。

2. 使用构建脚本生成可执行文件：

    ```bash
    .\build.bat
    ```

    构建完成的可执行文件位于 `dist/nightreign-overlay-helper` 目录下。


## 使用方法

双击 nightreign-overlay-helper.exe 运行程序，直接右键悬浮窗或右键任务栏图标打开菜单打开设置窗口，参考设置界面中的帮助进行配置。

## 安全性

本程序通过截屏识别游戏画面，并读取本机 Steam 连接元数据；不会修改游戏数据、读写游戏内存、注入代码或 Hook 游戏/Steam 进程。ETW 事件只在内存中处理，不生成 ETL 文件，也不显示或记录玩家 IP。任何第三方工具都无法保证反作弊风险绝对为零。

## 声明

- 本程序使用的图片资源所有版权归其合法所有者所有。
- 感谢来自 [Fuwish](https://github.com/Fuwishx) 的地图解包数据支持。
- 感谢来自 [雀煊](https://space.bilibili.com/391379672) 的大空洞水晶布局分享。
- P2P 连接查询及 ETW 延迟思路基于 MIT 许可的 [SteamP2PInfo](https://github.com/tremwil/SteamP2PInfo)。
