# L0 · 项目概览

## 目标

用“核心底座 + 插件 + 服务契约 + 事件总线”替换旧版 `nightreign-overlay-helper` 的巨型 `Updater`，解决以下问题：

| 旧版问题 | 重写方案 |
|---------|---------|
| 手写代码风格不统一 | `ruff`（lint + format）统一风格；全量类型标注；模块/类 docstring |
| 功能互相复杂依赖，`Updater` 是巨型协调者 | 核心底座 + 插件架构；插件间只通过服务契约与事件总线交互 |
| UI 难看 | PyQt-Fluent-Widgets (`PyQt6-Fluent-Widgets`) + `FluentWindow` |
| 无多语言 | 自研轻量 i18n：YAML 词条 + 命名空间 |
| 设置菜单平铺 | 主界面：首页 + 插件独立页 + 通用设置 + 关于 |

## 非目标（本阶段）

- 修改游戏内存
- 网络服务端
- Linux 正式支持

## 平台策略

- Windows 为主要目标平台。
- macOS 仅作开发调试降级：前台检测不可用、透明悬浮窗可能异常、屏幕录制权限缺失时功能受限。

## 目录结构

```
src/nightreign_overlay/
├── __main__.py / app.py      # 启动入口与应用生命周期
├── meta.py                   # 应用常量
├── core/                     # 与 UI 无关的基础设施
├── platforms/                # 平台差异封装
├── plugin/                   # 插件协议与管理器
├── ui/                       # 主界面、通用组件、悬浮窗基类
├── resources/                # 核心 i18n、图标
└── plugins/                  # 内置插件，每个插件一个子包
    └── <plugin_id>/
        ├── __init__.py       # 导出 PLUGIN 类
        ├── api.py            # 对外服务契约（其它插件只能 import 这里）
        ├── config.py         # 配置声明
        ├── plugin.py         # 生命周期实现
        ├── i18n/<lang>.yaml  # 插件词条
        └── tutorial/<lang>.md# 插件教程
```

## 依赖方向（INVARIANT）

```
UI / 插件 → plugin system → core → platforms
```

- Core 不依赖 UI 与插件。
- 插件之间只通过 `api.py` 建立服务契约，禁止直接导入实现。

## 技术栈

- Python ≥ 3.11（发布构建使用 3.13）
- PyQt6 + PyQt6-Fluent-Widgets
- numpy / opencv-python / Pillow
- mss（legacy 截图）
- pynput + pygame（全局热键/手柄）
- ruff（format + lint）
- pytest

## 相关文档

- 项目计划、旧版对照、阶段记录：[`REWRITE_PLAN.md`](./REWRITE_PLAN.md)
