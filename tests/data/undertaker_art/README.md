# 送葬者额外绝招检测样本

`0.png` 为 active 图标，`1.png` 至 `6.png` 为原有 inactive 图标。新增的 `inactive_scene_*.png` 均应判为 inactive，合计 1 张阳性、9 张阴性。

新反例从 `sandbox/undertaker/` 的完整游戏截图无损裁剪，仅保留生产自动区域 `art_timer.art_region`，未改变像素或缩放。坐标为相对于完整截图的 `(x, y, 宽, 高)`；自动区域按居中 16:9 客户区规则计算。

| 裁剪文件 | 来源 | 坐标 |
| --- | --- | --- |
| `inactive_scene_QQ20261024-005139.png` | `QQ20261024-005139.png` | `(735, 765, 87, 85)` |
| `inactive_scene_QQ20261024-005228.png` | `QQ20261024-005228.png` | `(636, 659, 75, 73)` |
| `inactive_scene_QQ20261024-005355.png` | `QQ20261024-005355.png` | `(637, 663, 76, 74)` |

`tests/plugins/test_undertaker_detector.py` 对每张图片保留原有 55 项检查，另运行饱和度（0.5、0.75、1、1.25、1.5）、对比度（0.6、1、1.4）、亮度（0.6、1、1.4）、清晰度（原图、7×7 σ=2 高斯模糊、1.8 倍原图减 0.8 倍模糊图锐化）的全部 135 种组合。增强函数集中在 `tests/support/undertaker_images.py`，与 `benchmark/benchmark_undertaker.py` 共享。

`tests/plugins/test_art_timer.py` 还将三张新反例通过插件截图事件流程分别作为 SDR／HDR 输入，检查不会触发 active、倒计时或延迟音频状态；该合成 HDR 输入检查不代表真实 HDR 截图验收。
