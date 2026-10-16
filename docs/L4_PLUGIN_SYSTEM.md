# L4 · 插件系统

## 职责

定义插件协议、管理插件发现/加载/激活/停用、解析依赖、提供插件上下文。

## 关键文件

| 文件 | 职责 |
|------|------|
| [`src/nightreign_overlay/plugin/base.py`](../src/nightreign_overlay/plugin/base.py) | `PluginManifest`, `Plugin`, `PluginKind`, `SettingsScope` |
| [`src/nightreign_overlay/plugin/context.py`](../src/nightreign_overlay/plugin/context.py) | `PluginContext`：插件 facade |
| [`src/nightreign_overlay/plugin/manager.py`](../src/nightreign_overlay/plugin/manager.py) | `PluginManager`：发现、拓扑排序、生命周期 |

## 插件分类

| `PluginKind` | 含义 | 默认启用 | 用户可开关 |
|--------------|------|---------|-----------|
| `INFRASTRUCTURE` | 基础能力（capture/input/hud/region） | 是 | 否 |
| `FEATURE` | 用户可见功能 | 是 | 是 |
| `DEBUG` | 调试/诊断工具 | 否 | 是 |

## 设置范围

| `SettingsScope` | UI 表现 |
|-----------------|---------|
| `PAGE` | 独立导航页 + 首页卡片 |
| `GENERAL` | 合并到通用设置页 |
| `HIDDEN` | 无直接入口，功能自身暴露操作 |

## 生命周期

```
discovered
   │
   ▼
loaded ──on_load()──▶ 绑定配置、加载状态
   │
   ▼ (PluginManager.start / set_enabled)
active ──on_activate()──▶ 注册服务、订阅事件、创建资源
   │
   ▼ (PluginManager.set_enabled / shutdown)
loaded ──on_deactivate()──▶ 停止工作；ctx.release() 自动清理
```

## PluginContext 托管资源

| 方法 | 释放时机 |
|------|---------|
| `config(...)` | 不自动释放；配置持久化 |
| `provide(api, impl)` | `deactivate` → `ctx.release()` 调用 `unregister_owner(plugin_id)` |
| `subscribe(event_type, handler)` | `deactivate` → 取消订阅 |
| `on_cleanup(callback)` | `deactivate` 后按反向顺序执行 |

## 依赖解析

- `PluginManager._resolve_order()` 对 `requires + optional` 做拓扑排序。
- 缺失强依赖或循环依赖的插件标记为 `UNAVAILABLE`。
- `set_enabled(id, True)` 会连带启用所有强依赖。
- `set_enabled(id, False)` 会先停用依赖它的插件。
- 基础设施插件始终启用，不接受用户开关。

## 插件间通信

### 服务契约

```python
# 提供方 plugins/foo/api.py
class FooApi:
    def do_something(self) -> None: ...


# 提供方 plugin.py
ctx.provide(FooApi, _FooService())

# 消费方（只能 import api.py）
foo = ctx.services.get(FooApi)
```

### 事件总线

```python
ctx.publish(DayStarted(day))
ctx.subscribe(DayStarted, on_day_started)
```

## INVARIANT

- 消费方插件只允许 import 提供方的 `api.py`，禁止导入其实现模块。
- `on_load()` 即使插件禁用也会调用，因此设置页能正常工作。
- `on_activate()` 可能失败；失败后 `ctx.release()` 会被调用，状态变为 `FAILED`。
- 插件启用状态持久化在 `plugin_manager.enabled`。

## PATTERN：新增一个插件

1. 在 `src/nightreign_overlay/plugins/` 下创建子包 `<plugin_id>/`。
2. 创建 `__init__.py` 导出 `PLUGIN = MyPlugin`。
3. 创建 `config.py` 定义 `ConfigGroup`。
4. 创建 `api.py` 定义对外契约（可选）。
5. 创建 `plugin.py` 实现 `Plugin` 子类，声明 `manifest`。
6. 创建 `i18n/zh_CN.yaml` 提供 `plugin.name`、`plugin.description` 及设置词条。
7. 创建 `tutorial/zh_CN.md`（可选）。

## PATTERN：插件使用基础能力

```python
# 申请截图流
capture = ctx.services.require(CaptureApi)
capture.acquire_stream(self.id)
ctx.on_cleanup(lambda: capture.release_stream(self.id))

# 注册热键
hotkeys = ctx.services.require(HotkeyApi)
hotkeys.register("my_plugin.action", HotkeyBinding(None), callback)
ctx.on_cleanup(lambda: hotkeys.unregister("my_plugin.action"))

# 添加 HUD 组件
hud = ctx.services.require(HudApi)
token = hud.add_widget(self.id, widget)
ctx.on_cleanup(lambda: hud.remove_widget(token))
```

## 常见修改场景

| 场景 | 应修改位置 |
|------|-----------|
| 新增插件 | `plugins/<id>/` + 遵循上述 PATTERN |
| 调整插件依赖 | `manifest.requires` / `manifest.optional` |
| 调整插件显示顺序 | `manifest.order` |
| 修改插件默认启用 | `manifest.default_enabled` |
| 调整插件 UI 入口 | `manifest.settings_scope` |
