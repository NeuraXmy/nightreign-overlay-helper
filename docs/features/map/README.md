# 地图信息

## 文件

- [`src/nightreign_overlay/plugins/map_detect/plugin.py`](../../../src/nightreign_overlay/plugins/map_detect/plugin.py)
- [`src/nightreign_overlay/plugins/map_detect/detector.py`](../../../src/nightreign_overlay/plugins/map_detect/detector.py)
- [`src/nightreign_overlay/plugins/map_detect/overlay.py`](../../../src/nightreign_overlay/plugins/map_detect/overlay.py)
- [`src/nightreign_overlay/plugins/map_detect/controls.py`](../../../src/nightreign_overlay/plugins/map_detect/controls.py)
- [`src/nightreign_overlay/plugins/map_detect/manual_filter.py`](../../../src/nightreign_overlay/plugins/map_detect/manual_filter.py)
- [`src/nightreign_overlay/plugins/map_detect/manual_catalog.py`](../../../src/nightreign_overlay/plugins/map_detect/manual_catalog.py)
- [`src/nightreign_overlay/plugins/map_detect/map_info.py`](../../../src/nightreign_overlay/plugins/map_detect/map_info.py)

## 职责

识别游戏内完整地图，显示地图信息、候选匹配结果、水晶布局。

## 依赖

`requires=("capture", "input", "region")`, `optional=("day_timer",)`

## 状态机

```
启用 / 重新标定 / Day1 / 重新识别 / 定时
                    │
                    ▼
                 PREPARE ──一次 check 后清空旧图──▶ TRUE
                                                   │
                            全图通过，且画面稳定 ≥0.6s
                                                   ▼
                                                terrain
                                                   │ 地形通过
                                                   ▼
                                                 FALSE
                                                   │
                                            POI、候选匹配与绘制
```

`PREPARE` 的截图不计入稳定窗口；`TRUE` 使用原始截图中心 80% 的 96×96 灰度缩略图，将其分成 4×4 块，以块平均绝对差的中位数判断主体变化。当前图同时与前一张和窗口起始图比较；高级选项中的「地图画面变化阈值」（默认 2 灰度级）决定何时重启窗口，「地图稳定时间」（默认 0.6 秒）决定所需稳定时长，允许少量局部标记变化。至少 3 张有效截图、采集时间跨度达到所设稳定时间才提交地形识别；默认 250 ms 截图间隔通常需要 4 张、跨度 0.75 秒。全图失败、识别请求、区域变化、标定、手动筛选切换及生命周期切换清除历史；非递增时间戳或超过 2.5 秒的采样断档也会清除历史。计时使用 `FrameCaptured.captured_at`，不把算法执行或回调积压当成稳定时间。地形及 POI 复用最新通过稳定检查的截图。

## 后台线程模型

- 单 `ThreadPoolExecutor(max_workers=1)` 串行检测。
- 忙碌时丢帧；通过 `_generation` 标记使过期结果无效。
- 停用时 `shutdown(wait=True, cancel_futures=True)` 等待原生 OpenCV 调用结束。

## 检测阶段

1. `check`：检测是否完整地图；定期触发匹配，在待识别状态确认画面稳定。
2. `terrain`：识别地形（`earth_shifting`）。
3. `<earth_shifting>`：基于地形匹配候选 POI 与水晶布局。

POI 算法由 `poi_algorithm` 配置选择，默认 `cnn`，保留 `template`。整图与手动筛选单点自动识别共用批量入口，CNN 使用 ONNX Runtime CPU。部署、类别约束、训练复现与验收结果见 [POI CNN](poi-cnn.md)。

## 地图悬浮窗

- `MapInfoOverlay`：显示地图绘制结果、候选 `#x/y`、水晶布局、识别状态。
- `ManualFilterOverlay`：覆盖地图区域的透明可交互筛选窗，选择特殊地形与 BOSS 后，可按位置设置据点基础图标和角标，也可对单点自动识别；右下角提示待选地形或当前剩余候选数，候选不超过 5 张时可“立刻应用”。
- `ManualFilterCatalog`：纯逻辑候选目录；合并相同基础图标，处理空据点、角标约束、有效选项与唯一值推断。
- `MapControlsOverlay`：紧贴当前地图类悬浮窗下方，提供重新识别、手动筛选、候选/水晶切换按钮。

设置页「地图识别」分组提供「进入强制显示模式／退出强制显示模式」按钮。启用插件并标定地图区域后，即使全图检测失败，也能保持地图信息悬浮窗与操纵栏显示，并通过操纵栏进入手动筛选；筛选期间显示手动筛选窗与操纵栏，应用结果后恢复地图信息显示。退出强制显示模式后，窗口重新跟随实际全图检测结果。该模式仅在本次启用期间有效，停用插件或重置设置时退出。

强制显示仅覆盖窗口的全图可见性门控，仍遵守全局前台显示设置；不会修改实际全图识别结果，也不会绕过后台的 `check → terrain → POI` 流程。全图检测失败时不自动提交地形或 POI 匹配，用户仍可手动筛选、应用候选和进行单点自动识别。

## 快捷键

设置页的「地图识别」分组保留区域标定卡片（含标定快捷键、区域状态和「标定」按钮），识别结果返回数量默认 3、范围 1–10。其他七项快捷键统一放入独立「快捷键」分组，仅保留绑定按钮；鼠标执行入口位于地图操控栏。

| action_id | 默认绑定 | 行为 |
|-----------|---------|------|
| `map_detect.calibrate_region` | 未绑定 | 标定地图区域 |
| `map_detect.recognize` | 未绑定 | 重新识别 |
| `map_detect.toggle` | 未绑定 | 切换地图悬浮窗显隐 |
| `map_detect.next_result` | 未绑定 | 下一个候选 |
| `map_detect.previous_result` | 未绑定 | 上一个候选 |
| `map_detect.next_crystal` | 未绑定 | 下一个水晶布局 |
| `map_detect.previous_crystal` | 未绑定 | 上一个水晶布局 |
| `map_detect.manual_filter` | 未绑定 | 进入／退出手动筛选模式 |

## 必须保持的约束

- 标定区域保存为正方形（按 DPI 截断到整数逻辑像素）。
- 候选/水晶切换快捷键检查地图悬浮窗可见性门控。
- 手动筛选期间强制隐藏地图信息、暂停自动识别；退出后恢复原显示状态。
- 据点约束只使用用户显式设置；候选共同决定的据点或角标仅作为显示推断，避免推断值反向锁死后续修改。
- 地形或 BOSS 改变、退出/重入、空候选重置都会递增手动筛选 revision；异步单点识别只接受同一 revision 的结果。
- 候选归零时保留地形与 BOSS、清空据点并提示；候选唯一时退出筛选并直接绘制该地图；立刻应用时按 pattern id 升序绘制全部剩余候选。
- 手动筛选窗与标定地图区域重合，背景透明但接收鼠标输入。
- 地图绘制名称使用 `i18n/<lang>-names.csv`，缺失回退中文。

## 地图数据与位置标注

地图数据位于 `src/nightreign_overlay/plugins/map_detect/data/csv/`，由 `map_info.load_map_info()` 加载：

| 数据 | 含义 |
| --- | --- |
| `map_patterns.csv` | 地图 ID、夜王、特殊地形、缩圈和事件 |
| `constructs.csv` | 地图与建筑／BOSS 的对应关系；`MAP` 是地图 ID，`type` 是类型，`row[4]` 是位置 ID |
| `positions.csv` | 位置 ID 对应的原始坐标，加载时转换到标准地图坐标 |
| `i18n/<lang>-names.csv` | 类型 ID 对应的显示名称；格式见[名称表说明](../../../src/nightreign_overlay/plugins/map_detect/i18n/README.md) |

查询 BOSS 点位时，先在名称表确定类型，再按地图 ID 和类型查 `constructs.csv`，最后用位置 ID 查坐标。不要把该表第一列的记录 ID 当成位置 ID。

`map_info.py` 中的 `TGH_UNDERGROUND_COORDS` 按位置 ID 标记大空洞地下点位；绘制时使用 `↓` 前缀和地下配色，地下建筑也不参与大空洞 POI 识别。位置标记会作用于引用该位置的所有地图。

测试入口与样本约定见[地图识别测试](../../development/testing/map-detection.md)。

[返回功能索引](../README.md)
