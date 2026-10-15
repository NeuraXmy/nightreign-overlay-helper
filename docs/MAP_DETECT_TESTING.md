# 地图识别测试说明

本项目的地图识别测试覆盖地图插件状态机、特殊地形识别、旧版兼容性和地图数据绘制。测试样本存放在 [`tests/data/map_detect/`](../tests/data/map_detect/)，由 Git 跟踪；测试文档集中放在 `docs/`，便于后续修改算法时查阅和扩展。

## 特殊地形样本

样本来自 `sandbox/old_test_data/test_map_image`，目前共 15 张图片。PNG 样本已转换为 RGB JPEG（quality=95、subsampling=0），原有 JPEG 保持原文件内容。此前错误命名的 `12_2.jpg` 已更正为 `1137_2.jpg`。

文件名按 `_` 分割后的第一段记录 ground truth 地图模式 ID：

- `1137.jpg` 表示只接受地图模式 `1137`。
- `1126-1176_hide.jpg` 表示识别出 `1126` 或 `1176` 都算正确。
- 文件名包含 `hide` 表示夜王信息隐藏；本组回归测试只验证特殊地形，因此不依赖夜王识别。

文件名中的数字是地图模式 ID，不是特殊地形 ID。测试会从程序加载的地图模式数据中取得对应的 `earth_shifting`，再与检测结果比较。

## 测试脚本

### `tests/test_map_terrain.py`

这是特殊地形算法的样本回归测试：

1. 逐张读取 `tests/data/map_detect/*.jpg`。
2. 根据文件名解析一个或多个地图模式 ID。
3. 通过 `MapDetector.info.patterns` 获取这些模式对应的特殊地形集合。
4. 调用完整的 `MapDetector.detect()` 流程，而不是只调用内部匹配函数。
5. 默认使用 NCC 算法，检查返回的特殊地形属于 ground truth，并检查分数通过 NCC 默认阈值。
6. 额外验证 NCC 和模板匹配的阈值互不影响，以及纯色无结构图像会被 NCC 拒绝。

NCC 返回原始归一化相关系数，范围是 `[-1, 1]`，越高越匹配；当前默认阈值为 `0.4`。模板匹配继续返回原有误差分数，越低越匹配，默认误差阈值为 `50`。两种算法的配置项和阈值分开保存。

运行单项测试：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_map_terrain.py -q
```

### `tests/test_map_nightlord.py`

这是当前夜王模板匹配算法的准确率测试，复用上述 15 张地图截图，直接调用生产代码的 `MapDetector._match_nightlord()`：

1. 使用 PIL 将截图读为 RGB 数组，保留完整地图裁剪；由生产函数完成缩放、左下角夜王区域裁剪和多尺度模板匹配。
2. 普通样本从文件名解析地图模式 ID，通过 `MapDetector.info.patterns` 取得对应的 `nightlord` 作为期望值；多个模式对应的夜王均可接受。
3. **文件名含独立 `hide` 标记的样本只接受 `None`，即 `icons/nightlord/unk.png` 对应的隐藏夜王，不使用地图模式的真实夜王作为期望值。**
4. 不运行地图候选匹配或 POI 推断，不使用地图 ID 修正识别结果。算法返回的夜王 ID 直接与期望值比较，分数必须为有限数。
5. 输出每张截图的期望值、实际值和匹配误差分数，以及总体、可见夜王和隐藏夜王三组准确率。每张截图独立断言，误识别会导致 pytest 失败，不跳过或标记为预期失败。

运行命令（即使不加 `-s`，也会输出准确率和逐样本报告）：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_map_nightlord.py -q
```

如果本机 Python 在 pytest 启动阶段的 `_readline_workaround` 导入 `readline` 时发生段错误，可禁用 capture 插件后运行同一组测试：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture tests/test_map_nightlord.py -q
```

2026-10-15 本地实测结果：

| 分组 | 正确 / 样本数 | 准确率 |
|------|---------------|--------|
| 总体 | 15 / 15 | 100.00% |
| 可见夜王 | 12 / 12 | 100.00% |
| 隐藏夜王（unk.png） | 3 / 3 | 100.00% |

隐藏样本的逐张结果（误差分数越低越匹配）：

| 样本 | 期望值 | 实际值 | 匹配分数 |
|------|--------|--------|----------|
| `1126-1176_hide.jpg` | `None`（unk.png） | `None`（unk.png） | 0.091471 |
| `207_hide.jpg` | `None`（unk.png） | `None`（unk.png） | 0.039759 |
| `251_hide.jpg` | `None`（unk.png） | `None`（unk.png） | 0.107766 |

当前函数将普通和深夜夜王图标映射到相同的数字 ID，因此该测试衡量夜王 ID 和隐藏状态的准确率，不区分普通与深夜图标。该函数没有分数拒识阈值，测试不会额外引入阈值。以上结果仅代表这组固定截图，不代表所有实机截图的准确率或所有夜王类别均已覆盖。

### `tests/test_map_detect.py`

验证地图插件的常规行为，包括：

- 设置页构建、算法下拉框和配置重置；
- 地图区域标定、检测状态机和异步任务提交；
- 地图覆盖层、手动筛选和快捷键联动；
- 检测结果更新、候选地图切换和水晶布局切换；
- 插件激活、停用、资源注册与释放。

### `tests/test_map_detect_legacy_parity.py`

在旧版源码目录存在时运行。它会隔离加载旧版检测器，将旧版和重写版放在相同地图数据、随机种子和图像上比较，覆盖：

- 完整地图和夜王检测；
- 模板匹配模式下的特殊地形检测；
- 地图候选排序、POI 类型和绘制结果；
- 地图数据、图标和水晶布局的迁移一致性。

该文件验证的是旧版兼容性，不约束 NCC 与旧模板匹配算法产生相同的分数或排序。旧版目录缺失时，测试会自动跳过。

## 推荐验证顺序

修改特殊地形算法或阈值时，先运行样本回归，再运行地图插件测试和旧版对照测试：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_map_terrain.py tests/test_map_detect.py -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_map_detect_legacy_parity.py -q
```

提交前还应运行：

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
git diff --check
```

当前样本覆盖六类特殊地形，并要求默认 NCC 在这 15 张图片上全部正确；这属于固定样本回归指标，不代表对所有实机截图的准确率保证。新增截图时，应同时将图片放入 `tests/data/map_detect/`，按照上述命名规则标注，并更新本文件的样本数量或特殊情况说明。
