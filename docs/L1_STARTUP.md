# L1 · 启动与生命周期

## 职责

管理应用从进程启动到退出的完整生命周期，包括命令行解析、单实例锁、核心服务构造、插件加载、主窗口与托盘显示、有序退出与重启。

## 关键文件

| 文件 | 职责 |
|------|------|
| [`src/nightreign_overlay/__main__.py`](../src/nightreign_overlay/__main__.py) | Windows 管理员权限检查、屏蔽 qfluentwidgets 启动横幅，调用 `app.run()` |
| [`src/nightreign_overlay/platforms/elevation.py`](../src/nightreign_overlay/platforms/elevation.py) | 使用 Windows UAC 请求管理员权限，处理取消与启动失败 |
| [`src/nightreign_overlay/app.py`](../src/nightreign_overlay/app.py) | `Application` 类：构造所有长生命周期对象、连接信号、启动、退出、重启 |
| [`src/nightreign_overlay/meta.py`](../src/nightreign_overlay/meta.py) | 应用常量：ID、名称、版本、游戏窗口标题 |
| [`src/nightreign_overlay/core/single_instance.py`](../src/nightreign_overlay/core/single_instance.py) | 单实例锁 |

## 启动调用链

```
__main__.main()
  ├─ ensure_administrator()    # Windows 未提权时请求 UAC，交接成功或失败后退出原进程
  └─ app.run(argv)
       ├─ parse_args(argv) → --minimized, --data-dir, --debug
       ├─ setup_logging(log_dir(), level)
       ├─ QApplication 创建
       ├─ SingleInstance(APP_ID).acquire()
       │     └─ 若已存在实例：发送激活信号并退出
       └─ Application(qt_app, instance, args)
            ├─ ConfigStore(settings_file())
            ├─ AppConfig 绑定
            ├─ 翻译初始化 + 主题应用
            ├─ create_backend() → PlatformBackend
            ├─ EventBus / ServiceRegistry
            ├─ GameWindowMonitor(backend, events)
            ├─ OverlayManager(backend, config, game_monitor)
            │     └─ ForegroundPolicy(config, monitor)
            ├─ 注册核心服务：PlatformBackend, AppConfig, GameWindowMonitor, ForegroundPolicy, OverlayManager
            ├─ PluginManager(...)
            │     ├─ discover()   扫描内置插件
            │     └─ load_all()   拓扑排序并 on_load()
            ├─ MainWindow(...)
            └─ TrayIcon(window)
                 └─ 连接信号
```

## Application.start()

Windows 默认以管理员权限运行，以满足联机延迟 ETW 的要求。打包 EXE 使用 `uac_admin=True` 启动清单；源码入口（`python main.py`、`python -m nightreign_overlay`）在构造 Qt 界面、创建单实例锁和启动插件前，通过 `ShellExecuteW("runas")` 请求提权。保留原 Python 启动参数、应用参数和工作目录。已提权进程直接继续，macOS 不请求提权。用户取消 UAC 或交接失败时显示说明并退出，不启动无权限实例。

```
start()
  ├─ game_monitor.start()      # 启动前台轮询
  ├─ plugins.start()           # 按依赖顺序激活已启用插件
  ├─ tray.show()               # 若系统托盘可用
  └─ window.show()             # 未最小化时显示主界面
```

## Application.quit() / restart()

```
quit()
  ├─ window.prepare_quit()     # 标记 _quitting=True，后续 closeEvent 接受
  ├─ _shutdown()
  │     ├─ plugins.shutdown()
  │     ├─ game_monitor.stop()
  │     ├─ tray.hide()
  │     └─ store.flush()
  └─ qt_app.quit()

restart()
  ├─ _shutdown()
  ├─ instance.release()        # 必须先释放单实例锁
  ├─ QProcess.startDetached(program, arguments, cwd)
  ├─ window.prepare_quit()
  └─ qt_app.quit()
```

## 信号连接

| 信号 | 含义 |
|------|------|
| `SingleInstance.activationRequested` | 单实例激活 → `window.bring_to_front()` |
| `OverlayManager.mainWindowRequested` | 悬浮窗右键“打开主界面” |
| `OverlayManager.mainWindowHideRequested` | 区域标定前隐藏主窗口 |
| `OverlayManager.mainWindowShowRequested` | 区域标定后恢复主窗口 |
| `OverlayManager.quitRequested` | 悬浮窗右键“退出” |
| `MainWindow.hiddenToTray` | 主窗口被隐藏到托盘 |
| `MainWindow.quitRequested` | 主窗口显式退出 |
| `SettingsPage.restartRequested` | 语言等需要重启生效的设置变更 |

## INVARIANT

- `Application` 持有所有长生命周期对象；禁止再引入全局单例。
- 单实例锁在 `restart()` 前必须释放，否则新进程只会激活旧进程。
- 主窗口普通关闭事件统一改为隐藏到托盘；只有 `_quitting=True` 时才接受关闭。

## PATTERN：新增一个启动时需要的长生命周期对象

1. 在 `Application.__init__` 中创建。
2. 若对象需要被插件使用，通过 `self.services.register(ApiClass, instance)` 注册。
3. 若对象需要周期运行，在 `start()` 中启动，在 `_shutdown()` 中停止。
4. 若对象持有资源，在 `_shutdown()` 中释放或添加 cleanup 回调。

## 常见修改场景

| 场景 | 应修改位置 |
|------|-----------|
| 新增命令行参数 | `app.parse_args()` |
| 新增核心级服务 | `Application.__init__` + `start()`/`_shutdown()` |
| 修改退出顺序 | `Application._shutdown()` |
| 修改主窗口关闭行为 | `MainWindow.closeEvent()`（见 L7_UI.md） |
