# 血条长度识别

血量阈值标记根据完整的可用血条长度绘制低血量、高血量和满血参考线。可用长度包含保有血、短暂掉血、可恢复血与空血，排除灰色扣血上限区域和血条外的场景。

## 插件与展示

`hp_marker` 依赖 `capture`、`input` 与 `region`，使用独立的 `HpMarkerOverlay`。标记始终鼠标穿透，由标定框定位，不使用普通悬浮窗的拖动位置持久化；窗口遵守统一的前台显示门控。

## 设置与输入

在“血量阈值标记”中标定血条：左边缘紧贴血条起点，高度与血条一致，宽度不限。生产截图向上下各补一倍标定高度，向右扩展至“检测区域宽高比 × 标定高度”，默认 125 倍；裁剪同时受所在显示器和当前截图帧的物理边界约束。保留负坐标副屏和混合 DPI 的设备像素约定。

当前只提供一套结构／材质检测流程，已移除旧版算法及切换选项。完整截面优先走 ONNX 材质分割与端点验证；旧窄裁剪保留水平扫描线兼容路径。实现细节与训练边界见 [血条材质分割与端点检测](material-detection.md)。

检测长度使用物理像素，绘制时换算为 Qt 逻辑坐标。检测偏移默认 3 像素，可在 -20 到 20 之间调整。低／高血量参考线比例在高级选项中设置，默认 40%／85%。标记为顶部平、底部尖的楔形，可调整颜色和大小；标记大小默认 100%，范围 50%–300%，同时缩放宽高。

## 拒识行为

检测器需要连续帧确认，且每次输出必须有当前帧证据。拒识时保留之前显示的标记；首次成功之前不显示标记。保留旧标记不代表当前帧已重新测量成功。重置设置、重新标定和停用会清理相关状态；异步任务通过 generation 丢弃过期结果。

## 实现入口

- [material.py](../../../src/nightreign_overlay/plugins/hp_marker/material.py)：ONNX 模型、有序材质分割、端点验证与连续确认。
- [material_features.py](../../../src/nightreign_overlay/plugins/hp_marker/material_features.py)：相对外观特征。
- [tracking.py](../../../src/nightreign_overlay/plugins/hp_marker/tracking.py)：材质路径与窄裁剪扫描线跟踪。
- [structural.py](../../../src/nightreign_overlay/plugins/hp_marker/structural.py)：扫描线边界估计。
- [plugin.py](../../../src/nightreign_overlay/plugins/hp_marker/plugin.py)：实际截图范围、串行后台检测及覆盖标记。
- [config.py](../../../src/nightreign_overlay/plugins/hp_marker/config.py)：显示选项和工作线程配置快照。

## 回归与限制

静态截图、合成变化、复杂背景和生产视频分别覆盖不同能力，不能用参与训练的视频回归代替新录像泛化评估。GT 只参与测试评分，不作为运行时输入；现有像素误差、拒识率、冷启动及最长拒识的统计继续保留。

生产黄血复杂背景仍可能出现较高拒识率和数秒的连续拒识，粉血冷启动也存在拒识窗口。当前测试将部分范围定义为 warning，测试通过不意味着每帧都输出。2026-10-19 审计数据见 [发布前检查 A18](../../development/releases/2026-10-19-audit.md#a18-血条生产回归仍包含明显的拒识限制)，优化记录见 [优化状态](../../development/experiments/hp/optimization-status.md)。

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/plugins/test_hp_material.py tests/plugins/test_hp_complex_scenes.py tests/plugins/test_hp_production_videos.py tests/plugins/test_hp_marker.py -q
```

[返回功能索引](../README.md)
