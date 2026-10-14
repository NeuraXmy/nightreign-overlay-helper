# L6 · 功能插件层

> 功能插件 `kind=feature`，用户可在首页/导航中开关。每个插件通常依赖 capture、input、region，部分依赖 hud。

---

## 6.1 day_timer（缩圈倒计时）

### 文件

- [`src/nightreign_overlay/plugins/day_timer/plugin.py`](../src/nightreign_overlay/plugins/day_timer/plugin.py)
- [`src/nightreign_overlay/plugins/day_timer/api.py`](../src/nightreign_overlay/plugins/day_timer/api.py)
- [`src/nightreign_overlay/plugins/day_timer/config.py`](../src/nightreign_overlay/plugins/day_timer/config.py)
- [`src/nightreign_overlay/plugins/day_timer/detector.py`](../src/nightreign_overlay/plugins/day_timer/detector.py)

### 职责

检测 DAY I/II/III 横幅，启动四段进度条倒计时；提供 `DayTimerApi` 与阶段事件。

### 依赖

`requires=("capture", "hud", "input", "region")`

### 数据流

```
FrameCaptured
   │
   ▼
_on_frame()
   │
   ├─ 检查 auto_detect / 标定中 / region
   ├─ DayDetector.detect(image, region, language, threshold, hdr)
   │
   ▼
_detected_day(day)
   ├─ 若同 DAY 3 秒内重复：刷新 _phase_started，publish DayStarted
   └─ 否则 _start_day(day)
         ├─ publish DayStarted
         ├─ publish DayPhaseChanged
         └─ _update_timer()
```

### 状态

- `day: int | None`
- `phase: Phase | None`
- `_phase_started: float | None`
- 阶段：FIRST_CIRCLE_STABLE → FIRST_CIRCLE_SHRINK → SECOND_CIRCLE_STABLE → SECOND_CIRCLE_SHRINK → NIGHT_BOSS

### 快捷键

| action_id | 默认绑定 | 行为 |
|-----------|---------|------|
| `day_timer.next_day` | `ctrl+shift+d` | 切换到下一天 |
| `day_timer.forward` | `ctrl+shift+right` | 前进若干秒 |
| `day_timer.backward` | `ctrl+shift+left` | 后退若干秒 |
| `day_timer.calibrate_region` | 未绑定 | 标定 DAY 横幅区域 |

### INVARIANT

- 标定期间 `_calibrating=True` 暂停模板匹配。
- 同一 DAY 横幅 3 秒内重复命中视为刷新开始时间。
- 重置设置时恢复默认快捷键并清除标定区域。

---

## 6.2 rain_timer（雨中冒险计时）

### 文件

- [`src/nightreign_overlay/plugins/rain_timer/plugin.py`](../src/nightreign_overlay/plugins/rain_timer/plugin.py)
- [`src/nightreign_overlay/plugins/rain_timer/detector.py`](../src/nightreign_overlay/plugins/rain_timer/detector.py)
- [`src/nightreign_overlay/plugins/rain_timer/config.py`](../src/nightreign_overlay/plugins/rain_timer/config.py)

### 职责

通过血条区域 HLS 颜色统计判断是否处于“雨中”状态，并倒计时。

### 依赖

`requires=("capture", "hud", "input", "region")`

### 检测逻辑

1. 裁剪血条区域，转 HLS。
2. 按正常色/雨中色（各自亮/暗两端 ± 容差）统计像素占比。
3. 雨中占比 ≥ 最大占比 且 正常占比 ≤ 最小占比 → 判为雨中。
4. 反之判为非雨中；其余不改变状态。

### 状态机

- 识别为雨中且未计时 → 开始倒计时。
- 识别为非雨中且正在计时 → 停止计时。
- 倒计时到期只隐藏进度条，不自动停止。

### 颜色校准

- 冻结画面提供“正常颜色血条 / 雨中颜色血条”两个按钮。
- 取框内出现次数最多的 HLS，只写入当前 HDR 模式。
- 重置只重置当前模式。

### INVARIANT

- 颜色采样始终用原图，不做 HDR 映射。
- 校准值按 HDR 开关分别存储。

---

## 6.3 art_timer（绝招倒计时）

### 文件

- [`src/nightreign_overlay/plugins/art_timer/plugin.py`](../src/nightreign_overlay/plugins/art_timer/plugin.py)
- [`src/nightreign_overlay/plugins/art_timer/detector.py`](../src/nightreign_overlay/plugins/art_timer/detector.py)
- [`src/nightreign_overlay/plugins/art_timer/config.py`](../src/nightreign_overlay/plugins/art_timer/config.py)

### 职责

检测绝招图标，显示对应持续时间的倒计时。

### 依赖

`requires=("capture", "hud", "input", "region")`

### 检测逻辑

1. 绝招键按下后等待 500 ms。
2. 单次截图，裁剪绝招区域。
3. 五个绝招图标在 0.95–1.05 五个尺度做带 alpha 掩码的 TM_SQDIFF。
4. 最小分数低于阈值（默认 0.02）判为该绝招。
5. HDR 时先 `hdr_to_sdr()`。

### 绝招数据

女爵/隐士/复仇者：延迟 2s，持续 13s；学者 20s；执行者 15s；各有不同颜色文案。

### INVARIANT

- 识别不保持帧流；无帧时本次按键放弃。
- 不再保存调试截图，排查看日志分数。

---

## 6.4 map_detect（地图识别）

### 文件

- [`src/nightreign_overlay/plugins/map_detect/plugin.py`](../src/nightreign_overlay/plugins/map_detect/plugin.py)
- [`src/nightreign_overlay/plugins/map_detect/detector.py`](../src/nightreign_overlay/plugins/map_detect/detector.py)
- [`src/nightreign_overlay/plugins/map_detect/overlay.py`](../src/nightreign_overlay/plugins/map_detect/overlay.py)
- [`src/nightreign_overlay/plugins/map_detect/controls.py`](../src/nightreign_overlay/plugins/map_detect/controls.py)
- [`src/nightreign_overlay/plugins/map_detect/map_info.py`](../src/nightreign_overlay/plugins/map_detect/map_info.py)

### 职责

识别游戏内完整地图，显示地图信息、候选匹配结果、水晶布局。

### 依赖

`requires=("capture", "input", "region")`, `optional=("day_timer",)`

### 状态机

```
FALSE ──检测到完整地图──▶ PREPARE ──下一帧──▶ TRUE
  ▲                                            │
  └────────── 重新标定 / Day1 / 手动 / 定时 ────┘
```

### 后台线程模型

- 单 `ThreadPoolExecutor(max_workers=1)` 串行检测。
- 忙碌时丢帧；通过 `_generation` 标记使过期结果无效。
- 停用时 `shutdown(wait=True, cancel_futures=True)` 等待原生 OpenCV 调用结束。

### 检测阶段

1. `check`：检测是否完整地图；定期触发匹配。
2. `terrain`：识别地形（`earth_shifting`）。
3. `<earth_shifting>`：基于地形匹配候选 POI 与水晶布局。

### 地图悬浮窗

- `MapInfoOverlay`：显示地图绘制结果、候选 `#x/y`、水晶布局、识别状态。
- `MapControlsOverlay`：紧贴地图悬浮窗下方，提供重新识别、候选/水晶切换按钮。

### 快捷键

| action_id | 默认绑定 | 行为 |
|-----------|---------|------|
| `map_detect.calibrate_region` | 未绑定 | 标定地图区域 |
| `map_detect.recognize` | 未绑定 | 重新识别 |
| `map_detect.toggle` | 未绑定 | 切换地图悬浮窗显隐 |
| `map_detect.next_result` | 未绑定 | 下一个候选 |
| `map_detect.previous_result` | 未绑定 | 上一个候选 |
| `map_detect.next_crystal` | 未绑定 | 下一个水晶布局 |
| `map_detect.previous_crystal` | 未绑定 | 上一个水晶布局 |

### INVARIANT

- 标定区域时截成旧版规则的正方形（按 DPI 截断到整数逻辑像素）。
- 候选/水晶切换快捷键检查地图悬浮窗可见性门控。
- 地图绘制名称使用 `i18n/<lang>-names.csv`，缺失回退中文。

---

## 6.5 hp_marker（血量阈值标记）

### 文件

- [`src/nightreign_overlay/plugins/hp_marker/plugin.py`](../src/nightreign_overlay/plugins/hp_marker/plugin.py)
- [`src/nightreign_overlay/plugins/hp_marker/detector.py`](../src/nightreign_overlay/plugins/hp_marker/detector.py)
- [`src/nightreign_overlay/plugins/hp_marker/overlay.py`](../src/nightreign_overlay/plugins/hp_marker/overlay.py)
- [`src/nightreign_overlay/plugins/hp_marker/config.py`](../src/nightreign_overlay/plugins/hp_marker/config.py)

### 职责

检测血条长度，在血条上方绘制低/高/满血三条标记。

### 依赖

`requires=("capture", "input", "region")`

### 检测逻辑

1. 从选区左边缘开始，忽略宽度，截取 `height * 125` 宽度。
2. PIL LANCZOS 缩放到 15px 标准高度。
3. 中线 HSV V 通道，从第 30 像素开始检测亮度峰。
4. 聚类、平滑、稳定计数等历史处理。

### 独立悬浮窗

- `HpMarkerOverlay`：不拖动、不保存普通悬浮窗位置。
- 始终鼠标穿透。
- 接入统一前台门控（修复旧版遗漏）。

### INVARIANT

- 保留旧版失败保持行为：检测失败不更新显示，保留旧结果。
- 坐标/尺寸按屏幕 DPI 截断。
- 选区宽度被忽略。

---

## 6.6 p2p_latency（联机状态）

### 文件

- [`src/nightreign_overlay/plugins/p2p_latency/plugin.py`](../src/nightreign_overlay/plugins/p2p_latency/plugin.py)
- [`src/nightreign_overlay/plugins/p2p_latency/service.py`](../src/nightreign_overlay/plugins/p2p_latency/service.py)
- [`src/nightreign_overlay/plugins/p2p_latency/overlay.py`](../src/nightreign_overlay/plugins/p2p_latency/overlay.py)
- [`src/nightreign_overlay/plugins/p2p_latency/models.py`](../src/nightreign_overlay/plugins/p2p_latency/models.py)
- [`src/nightreign_overlay/plugins/p2p_latency/mock_helper.py`](../src/nightreign_overlay/plugins/p2p_latency/mock_helper.py)

### 职责

显示 Steam 联机队友、Ping、稳定度。

### 依赖

无截图/HUD 依赖；独立 `P2POverlay`。

### 架构

- Windows：启动原生 `NightreignP2PHelper` 子进程，通过 JSONL 协议通信。
- macOS：启动 `mock_helper.py` 模拟数据。
- `P2PService` 管理子进程、解析输出、维护状态/玩家列表。
- `P2POverlay` 显示状态与玩家列表。

### INVARIANT

- 联机检测不受截图门控影响；但悬浮窗仍受显示门控约束。
- macOS 明确显示为模拟数据，不伪装真实 ETW。
- 原生 C# 项目原样复制，未修改检测算法。

---

## 功能插件通用模式

### 标准 on_activate 结构

```python
def on_activate(self):
    # 1. 创建检测器/状态
    self._detector = MyDetector(...)

    # 2. 注册服务（若需要对外暴露）
    ctx.provide(MyApi, _MyService(self))

    # 3. 订阅事件
    ctx.subscribe(FrameCaptured, self._on_frame)
    ctx.subscribe(SomeOtherEvent, self._on_event)

    # 4. 申请资源并注册清理
    capture = ctx.services.require(CaptureApi)
    capture.acquire_stream(self.id)
    ctx.on_cleanup(lambda: capture.release_stream(self.id))

    # 5. 注册热键
    hotkeys = ctx.services.require(HotkeyApi)
    hotkeys.register("my_plugin.action", default, callback)
    ctx.on_cleanup(lambda: hotkeys.unregister("my_plugin.action"))

    # 6. 创建 HUD/独立悬浮窗
    hud = ctx.services.require(HudApi)
    token = hud.add_widget(self.id, widget)
    ctx.on_cleanup(lambda: hud.remove_widget(token))
```

### 后台线程模型

- 使用 `ThreadPoolExecutor(max_workers=1)` 串行执行原生/OpenCV 调用。
- 工作线程不读写 Qt 对象。
- 结果通过 `pyqtSignal` 回到主线程的 `_on_completed`。
- 使用 `_generation` 标记使过期结果无效。

### 区域标定模式

```python
def _calibrate_region(self):
    if self._calibrating:
        return
    self._calibrating = True
    self._generation += 1
    try:
        region = ctx.services.require(RegionApi).request_region(
            _REGION_KEY, label, color, screenshot_path=...
        )
        # 可能做后处理（如 map_detect 截成正方形）
    finally:
        self._calibrating = False
```

## 常见修改场景

| 场景 | 应查看/修改 |
|------|------------|
| 调整 DAY 检测逻辑 | `plugins/day_timer/detector.py` |
| 调整雨中颜色判断 | `plugins/rain_timer/detector.py` |
| 调整绝招图标/阈值 | `plugins/art_timer/detector.py` + `config.py` |
| 调整地图检测/绘制 | `plugins/map_detect/detector.py` + `map_info.py` |
| 调整地图 UI/操控栏 | `plugins/map_detect/overlay.py` + `controls.py` |
| 调整血条检测算法 | `plugins/hp_marker/detector.py` |
| 调整联机显示/状态 | `plugins/p2p_latency/service.py` + `overlay.py` |
