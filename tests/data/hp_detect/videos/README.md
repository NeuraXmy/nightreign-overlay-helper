# 血条视频与 GT

新增复杂背景测试集由 `scene_annotations.json` 独立描述，详见 [复杂背景评估](../../../../docs/development/experiments/hp/complex-scenes.md)：

- `hp_pink_complex.mkv`：来自 `2026-10-16 20-19-02.mp4`，红／粉／空血，无灰段，1835 帧，GT 恒定 425 px。源裁剪 `(18, 6, 1250, 30)` 保留主程序完整输入。
- `hp_yellow_complex.mkv`：来自 `hp_3.mp4`，红／黄／空血，无灰段，1404 帧，GT 恒定 320 px。源裁剪 `(8, 2, 712, 30)`；由于视频编码器会截断奇数宽度，存储时保留一个真实左侧上下文像素，评估时移除第一列，实际输入为 `(9, 2, 711, 30)`，右侧紧贴屏幕边界。

两者均为 30 FPS、FFV1 无损视频，不缩放、不删减可解码帧。制作时比较了全部解码像素的 SHA-256；标注还保存源文件／片段文件哈希、参考帧和标定坐标。`hp_*_annotation.png` 中青色线标记人工确认的左右端帽中心，`hp_*_frame_*.png` 为未修改参考裁剪。GT 不随当前彩色填充长度变化。

`scene_report.json` 保留旧高光算法的失败基线，`scene_geometry_report.json` 为仅外框原型的历史对照；`scene_failure_examples.png` 展示旧算法错误。当前四段联合回归结果见 `production_report.json`，复杂背景准确性测试已经移除 xfail，要求零误报、拒识低于 20%、最长拒识低于两秒。GT、无灰段和恒定长度标签都不会传入运行时检测器。

## 当前主程序四段联合验收

`production_annotations.json` 记录全部四段源录像的完整时长和实际标定／截图范围。带灰段的 `hp_footage_1_production.mkv`、`hp_footage_2_production.mkv` 分别完整保留 1067、953 帧，不再从源第 3 秒开始；沿用原来的稳定段人工 GT，过渡段仍供帧但不评分。

| 源录像 | 标定框 xywh | 实际截图 xywh | FFV1 存储范围 xywh |
| --- | --- | --- | --- |
| hp_1.mp4 | 83,30,5,8 | 83,22,637,24 | 82,22,638,24 |
| hp_2.mp4 | 117,32,5,8 | 117,24,603,24 | 116,24,604,24 |
| 2026-10-16 20-19-02.mp4 | 18,16,5,10 | 18,6,1250,30 | 18,6,1250,30 |
| hp_3.mp4 | 9,12,5,10 | 9,2,711,30 | 8,2,712,30 |

偶数宽存储的额外第一列在评估前去掉。制作时核对所有源裁剪像素，fixture 文件、完整解码像素流、源 MP4 及参考帧均有哈希／逐像素回归。粉血、黄血复用上面的完整场景 fixture。四段源 MP4 与 fixture 的全部预测和拒识统计一致。

`production_report.json` 为当前打包模型的三种频率连续播放和 136 组独立启动的完整记录。`heldout_block_report.json` 与 `heldout_training.json` 保存另一个模型对未参与训练的交替五秒时间块的结果及训练索引，**不是打包模型的同集结果**；其中仍有罕见特效误报。当前模型的来源、训练索引及文件哈希在 `src/nightreign_overlay/plugins/hp_marker/data/training.json`。

旧 `hp_footage_*.mkv` 缺少部分生产上下文，继续用于静态和连续裁剪兼容回归；冷启动主验收采用实际生产范围。直接输入旧窄裁剪时第一段仍有最坏窗口 52.63% 拒识、2.40 秒首次输出的限制，不能用生产 fixture 的成绩替换该结论。

```powershell
python -m tests.support.hp_production_evaluation --output .tmp/hp_production_report.json
python -m tests.support.hp_production_evaluation --source-dir sandbox --output .tmp/hp_source_report.json
```

另外新增 `rectangle_length_3.mkv` 用于扩大区域的二维血条实验，包含红血、粉血和空血，无扣上限灰段，GT 为 425 px。它的裁剪范围、标注和评估与下面两段 10 px 高的视频独立，详见 [矩形实验报告](../../../../docs/development/experiments/hp/rectangle.md) 及 `rectangle_annotations.json`。

两段录像的血条可用总长度分别固定为 **396 px**、**424 px**；当前血量、短暂掉血与场景会变化。GT 包含空血部分，不随红色或黄色填充长度变化。

| 测试视频 | 原始录像 | 实际可解码帧数 | FPS | GT |
|---|---|---:|---:|---:|
| `constant_length_1.mkv` | `2026-10-16 17-02-30.mp4` | 1773 | 30 | 396 |
| `constant_length_2.mkv` | `2026-10-16 17-04-14.mp4` | 1276 | 30 | 424 |

两段视频均从原图 `(0, 0)` 裁剪宽 1250、高 10 的区域，未缩放、未降帧，采用 FFV1 无损编码、不保留音频。裁剪右侧保留场景上下文，宽度符合默认检测比例 `125 × 10`，没有用 GT 限定输入宽度。制作时将原始视频与裁剪视频按解码顺序逐帧比较，所有裁剪像素完全一致。原始 MP4 容器的标称帧数均比实际可解码数多 1；此处记录实际读取数，没有丢弃可解码帧。

`annotations.json` 保存裁剪坐标、原始文件与裁剪视频 SHA-256、帧率、帧数、GT、参考帧以及验收标准。原始完整录像不作为测试依赖。

GT 独立于检测器预测：人工放大清晰帧，比较接近满血与掉血后的固定外端帽，将端帽中心标为可用血条终点。第一段参考第 360、700 帧，第二段参考第 0、700 帧，帧号从 0 开始。`*_frame_*.png` 为未标记、未缩放的参考裁剪；`*_gt.png` 从首张参考图左侧截取至人工标注终点，图宽即 GT。容差为原始像素 ±3，涵盖端帽抗锯齿与视频压缩造成的边缘模糊。

验收要求针对每段视频分别计算：所有有效输出误差不超过 3 px，拒识观测数不超过总观测数的 50%，连续拒识不超过 5 秒。连续拒识包含开头及结尾，按视频时间计算；250 ms 抽样使用源时间戳选择帧，不假设每隔固定整数帧采样。算法只接收图像，不接收视频编号、帧号、GT 或“长度不变”的标签。

在仓库根目录运行视频回归测试：

```bash
python -m pytest tests/plugins/test_hp_detection_video.py -q
```

两段录像均用于此次优化，结果不代表未见场景的泛化准确率。

增加 `--augmentations` 可复现之前截图测试的 32 组完整 RGB 图像增强，支持与 `--interval 0.25` 组合。每组单独新建检测器，缩放时同比调整 GT 与容差。`augmentation_full_report.json` 和 `augmentation_250ms_report.json` 保存完整结果，汇总见[连续视频增强评估](../../../../docs/development/experiments/hp/video-augmentation-2026-10-16.md)。存在不达标组时评估命令返回 1，不会修改算法或放宽测试标准。
