# Nightreign Overlay Helper

[中文README](#黑夜君临悬浮助手)

Nightreign Overlay Helper is a utility program developed with PyQt6, designed to display various useful information and features while playing the game, **currently supporting only the Chinese language**.

## Features

- Displays countdowns for night rain circle shrinking and fast damage of night rain, triggered by hotkeys or automatic detection.
- Map recognition and floating map information (new maps added in DLC are not supported).
- Displays health percentage markers corresponding to "trigger when health is low" and "trigger when health is full" entries.
- Displays countdowns for art buffs of certain characters.

## Build Instructions

#### Prerequisites
- Windows 7, 8, 10, or 11
- Python 3.10 or higher

#### Steps

1. Clone the repository and navigate to the project directory.

2. Install the required dependencies:

    ```bash
    pip install -r requirements.txt
    ```

3. Build the executable using build script:

    ```bash
    .\build.bat
    ```

    You can find the built executable in the `dist/nightreign-overlay-helper` directory.


## Usage
Double-click `nightreign-overlay-helper.exe` to run the program. Right-click the overlay window or the taskbar icon to open the menu and access the settings window. Refer to the help in the settings UI for configuration guidance.

## Safety
The program recognizes game information by capturing screenshots of the game screen, without modifying game data or reading/writing to game memory.

---

# 黑夜君临悬浮助手

[English README](#Nightreign-Overlay-Helper)

基于PyQt6开发的用于在游戏中显示各种实用信息和功能的辅助程序，目前界面仅支持中文语言。

## 功能

- 显示缩圈和雨中冒险倒计时，支持快捷键触发或自动检测。
- 地图识别与地图信息悬浮（DLC添加的新地图暂不支持识别）。
- 显示“血量较低触发”与“满血时触发”的词条对应百分比血量位置标记。
- 显示部分角色的绝招buff倒计时。

## 构建

#### 环境要求

- Windows 7、8、10 或 11
- Python 3.10 及以上版本

#### 构建步骤

1. 克隆代码库并进入项目目录。

2. 安装所需依赖：

    ```bash
    pip install -r requirements.txt
    ```

3. 使用构建脚本生成可执行文件：

    ```bash
    .\build.bat
    ```

    构建完成的可执行文件位于 `dist/nightreign-overlay-helper` 目录下。


## 使用方法

双击 nightreign-overlay-helper.exe 运行程序，直接右键悬浮窗或右键任务栏图标打开菜单打开设置窗口，参考设置界面中的帮助进行配置。

## 安全性

本程序的游戏信息识别通过截屏游戏画面实现，不涉及对游戏数据的修改或对游戏内存的读写。
