# 计时功能

缩圈、雨中冒险与绝招计时通过共享 HUD 显示，各自管理检测状态、快捷键和音频配置。

## 音频播报

- day_timer、rain_timer、art_timer 设置页末尾均有独立“音频播报”组；每张卡片分别保存本地文件路径、音量（默认 100%）和时间偏移（默认 0.0 秒）。音频未设置时不播放。支持更换、清空文件以及立即测试播放。
- 缩圈计时有 5 项：DAY I、II、III 开始（延迟），一缩、二缩开始（提前；两天共用）。开始时间跟随横幅识别刷新；同一轮横幅重复识别不会重复播报。手动切换天数、前进和后退均使用同一调度逻辑，回退不重复已播报的提示。
- 雨中冒险有 2 项：开始（延迟）、结束（提前）。结束提前量相对于配置的倒计时时长；检测或手动操作提前结束时，尚未播报的结束提示立即播放，并取消未到时的开始提示。
- 绝招计时有 2 项：倒计时开始（延迟）、结束（提前）。偏移以绝招实际效果开始和结束为基准，包含角色固有的效果启动延迟。
- 超过计时时长的提前量按本轮开始处理。同一轮每项最多播报一次；重新开始或禁用功能会清除本轮调度，禁用同时停止该功能正在播放的音频。
- 配置通过各插件上下文绑定到 `plugins.<id>.audio.<cue>` 命名空间，页面重置会恢复全部音频默认值。
- 隐藏基础设施插件 audio 提供 AudioApi，使用现有 PyQt6 的 QtMultimedia，无额外 Python 依赖。所有功能和播放测试共用一个播放器，新音频替换正在播放的音频。播放器延迟到首次播放时创建；文件缺失、解码失败或后端不可用记录日志，不中断计时。支持格式以本机 Qt 多媒体后端为准。

## day_timer（缩圈倒计时）

### 文件

- [`src/nightreign_overlay/plugins/day_timer/plugin.py`](../../src/nightreign_overlay/plugins/day_timer/plugin.py)
- [`src/nightreign_overlay/plugins/day_timer/api.py`](../../src/nightreign_overlay/plugins/day_timer/api.py)
- [`src/nightreign_overlay/plugins/day_timer/config.py`](../../src/nightreign_overlay/plugins/day_timer/config.py)
- [`src/nightreign_overlay/plugins/day_timer/detector.py`](../../src/nightreign_overlay/plugins/day_timer/detector.py)

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
| `day_timer.next_day` | 未设置 | 切换到下一天 |
| `day_timer.forward` | 未设置 | 前进若干秒 |
| `day_timer.backward` | 未设置 | 后退若干秒 |
| `day_timer.calibrate_region` | 未绑定 | 标定 DAY 横幅区域 |

### 必须保持的约束

- 标定期间 `_calibrating=True` 暂停模板匹配。
- 同一 DAY 横幅 3 秒内重复命中视为刷新开始时间。
- 重置设置时恢复默认快捷键并清除标定区域。

## rain_timer（雨中冒险计时）

### 文件

- [`src/nightreign_overlay/plugins/rain_timer/plugin.py`](../../src/nightreign_overlay/plugins/rain_timer/plugin.py)
- [`src/nightreign_overlay/plugins/rain_timer/detector.py`](../../src/nightreign_overlay/plugins/rain_timer/detector.py)
- [`src/nightreign_overlay/plugins/rain_timer/config.py`](../../src/nightreign_overlay/plugins/rain_timer/config.py)

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

### 必须保持的约束

- 颜色采样始终用原图，不做 HDR 映射。
- 校准值按 HDR 开关分别存储。

## art_timer（绝招倒计时）

### 文件

- [`src/nightreign_overlay/plugins/art_timer/plugin.py`](../../src/nightreign_overlay/plugins/art_timer/plugin.py)
- [`src/nightreign_overlay/plugins/art_timer/detector.py`](../../src/nightreign_overlay/plugins/art_timer/detector.py)
- [`src/nightreign_overlay/plugins/art_timer/config.py`](../../src/nightreign_overlay/plugins/art_timer/config.py)

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

### 必须保持的约束

- 识别不保持帧流；无帧时本次按键放弃。
- 识别截图通过统一调试图片服务保存，结果名为 `art_timer_ultimate`；日志记录识别分数。

[返回功能索引](README.md)
