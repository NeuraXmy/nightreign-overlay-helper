# 调试图片存储与保留

应用通过 `src/nightreign_overlay/core/debug.py` 中的 `DebugImageApi` 异步保存诊断图片。保存默认开启，可在通用设置中关闭；关闭后忽略新的保存请求，已有文件仍可通过[诊断导出](diagnostic-export.md)打包。

## 存储约定

- 根目录：`user_data_dir()/debug`，各结果单独存入 `debug/{result_name}/`。
- 文件名：时间戳，例如 `20261016_153012_123456.jpg`；同名 `.json` 保存元数据。JPEG 质量为 85。
- 默认每种结果保留 10 组图片与元数据，可用 `keep` 覆盖；标定使用 `keep=1`。
- `cooldown_seconds` 限制同种结果的提交频率；元数据保存识别分数或比例，标定还记录屏幕几何、DPR、截图原点和选区。
- NumPy 图片通过 `write_cv2_image()` 编码后使用 Python 文件 I/O 写入，兼容 Windows 中文用户目录；Qt 与 Pillow 使用各自支持 Unicode 的保存方法。

## 资源与关闭行为

单个后台线程负责转换、压缩、写入元数据和清理过期文件。提交方承担图片快照和入队成本，检测线程与 GUI 线程不执行磁盘写入。

包括正在写入的任务在内，最多接受 8 个任务、64 MiB 图片快照；超限在复制图片前返回 `False`。关闭后拒绝新提交，调用线程最多等待 1 秒，然后取消尚未开始的任务。已开始的底层写入无法强制中断，会在后台完成；解释器退出仍可能等待该写入。

## 结果目录

| 结果 | 目录名 | 保留数／冷却 |
| --- | --- | --- |
| 区域标定 | `region_{region_key}`、`region_sample_{sample_key}` | 1／无 |
| DAY 横幅 | `day_timer_dayx` | 10／10 分钟 |
| 雨中血条颜色 | `rain_timer_hp_color` | 10／10 分钟 |
| 绝招识别 | `art_timer_ultimate` | 10／10 分钟 |
| 完整地图 | `map_full_map` | 10／10 分钟 |
| 特殊地形 | `map_terrain` | 10／无 |
| 夜王 | `map_nightlord` | 10／无 |
| POI 输入与结果 | `map_poi`、`map_poi_result` | 10／无 |
| 血量标记 | `hp_marker` | 10／10 分钟 |

图片提交开销随输入尺寸、格式和机器负载变化；后台保存不能保证零调用开销，单次机器上的计时不作为性能承诺。

[返回指南索引](README.md)
