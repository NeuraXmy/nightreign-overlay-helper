# 计时功能

缩圈、雨中冒险与绝招计时通过共享 HUD 显示，各自管理检测状态、快捷键和音频配置。

## 音频播报

- day_timer、rain_timer、art_timer 设置页末尾均有独立“音频播报”组。软件内置 10 条中文语音，随源码和运行 ZIP 一同分发；每项默认关闭、音量 100%，可按需开启、试听、选择自定义文件或恢复默认音频。已有开关和自定义设置保持不变。完整对应关系见 [资源清单](../../src/nightreign_overlay/plugins/audio/sounds/README.md)。
- 缩圈计时有 5 项：DAY I、II、III 开始（默认延迟 0 秒），一缩、二缩开始（默认提前 30 秒；两天共用）。开始时间跟随横幅识别刷新；同一轮横幅重复识别不会重复播报。手动切换天数、前进和后退均使用同一调度逻辑，回退不重复已播报的提示。
- 雨中冒险有 3 项：开始（默认延迟 0 秒）、即将结束（默认提前 30 秒）、结束（默认提前 0 秒）。提前量相对于配置的倒计时时长；检测或手动操作提前离开雨区时，只播放尚未播报的结束提示，取消未到时的开始/预警。正常到期播报结束后，再离开雨区不会重复。
- 绝招计时有 2 项：效果开始（默认延迟 0 秒）、结束预警（默认提前 3 秒）。偏移以绝招实际效果开始和结束为基准，包含角色固有的效果启动延迟。
- 超过计时时长的提前量按本轮开始处理。同一轮每项最多播报一次；重新开始或禁用功能会清除本轮调度，禁用同时停止该功能正在播放的音频。
- 配置通过各插件上下文绑定到 `plugins.<id>.audio.<cue>` 命名空间。空 `path` 使用软件内置资源，安装路径不写入配置，完整移动软件目录后仍有效；已有自定义路径、音量、时间和明确关闭状态保留。页面重置恢复每项各自的默认提前量。修改提前量时需自行选择内容对应的录音。
- 关闭单项立即停止该项正在播放的语音或试听，不影响其它项；关闭期间到时的提示被消耗，重新开启不会补播。自定义文件不存在时记录失败，不悄悄换成默认语音；可点“恢复默认音频”重新启用内置资源。
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
- [`src/nightreign_overlay/plugins/art_timer/undertaker_detector.py`](../../src/nightreign_overlay/plugins/art_timer/undertaker_detector.py)
- [`src/nightreign_overlay/plugins/art_timer/config.py`](../../src/nightreign_overlay/plugins/art_timer/config.py)

### 职责

检测绝招图标，显示对应持续时间的倒计时。

### 依赖

`requires=("capture", "hud", "input", "region", "audio")`

### 检测逻辑

1. 绝招键按下后等待 500 ms。
2. 单次截图，裁剪绝招区域。
3. 五个绝招图标在 0.95–1.05 五个尺度做带 alpha 掩码的 TM_SQDIFF。
4. 最小分数低于阈值（默认 0.02）判为该绝招。
5. HDR 时先 `hdr_to_sdr()`。

送葬者额外绝招检测默认开启，独立于上述快捷键和模板匹配流程，持续读取同一个绝招区域。图标先缩小为 32×32，再按 HSV 紫色至品红色范围统计像素占比（OpenCV H=135–150、S≥12、V≥40），排除偏红场景染色落入原先过宽色调范围引起的误触发；达到默认 80% 阈值时立即开始默认 3.8 秒倒计时，开始后等待计时自然结束，变为 inactive 或暂时无法获取图标区域均不会提前取消。高级选项可调整占比阈值和持续时间，持续时间支持浮点数（1–60 秒）。计时期间再次进入 active 不会重置计时；计时结束后需检测到新的 inactive → active 变化才会再次触发。关闭检测或停用插件仍会立即取消计时。

送葬者复用现有绝招计时条，进度颜色为图标粉色 `#c28aba`。其计时期间优先显示，结束后恢复仍未到期的普通绝招计时；普通绝招的计时及音频继续独立运行。

音频播报组提供“送葬者额外绝招倒计时开始”定长音频选项，默认关闭，需自行选择音频文件。开启后每次开始倒计时时按设置的延迟秒数播放一次，默认延迟 0 秒，可设置音量并试听。延迟从倒计时启动时计算，即使超过倒计时长度也会在延迟到达后播放；关闭检测或停用插件会取消尚未触发的播放。它与其他定长音频共用播放器，互相替换，与循环音频可同时播放。

回归样本位于 `tests/data/undertaker_art/`，包含 1 张 active、9 张 inactive，其中 3 张新反例为偏红背景和受场景染色的未激活图标。保留原有 55 项检查，另覆盖饱和度 0.5–1.5 倍、对比度和亮度各 0.6–1.4 倍、原图／模糊／锐化的全部 135 种组合。性能复测使用 `uv run python benchmark/benchmark_undertaker.py`；详细范围及结果见[送葬者检测验证记录](../development/testing/undertaker-detection-2026-10-23.md)。这些结果用于验证已有样本的容错，新增游戏截图仍应加入回归测试。

### 绝招数据

女爵/隐士/复仇者：延迟 2s，持续 13s；学者 20s；执行者 15s；各有不同颜色文案。

### 必须保持的约束

- 普通模板识别不保持帧流；无帧时本次按键放弃。送葬者检测开启时保持共享帧流，关闭检测或停用插件时释放。
- 识别截图通过统一调试图片服务保存，结果名为 `art_timer_ultimate`；日志记录识别分数。

[返回功能索引](README.md)
