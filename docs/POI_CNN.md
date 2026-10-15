# POI CNN 部署与验收

地图识别增加 `poi_algorithm` 配置：`cnn`（默认）或 `template`，设置页显示名称为“CNN”和“模板匹配”。运行时仅新增 `onnxruntime` 依赖，不依赖 PyTorch、ONNX 导出工具或训练代码。

## 识别流程

1. 沿用地形、夜王检测与 750×750 地图对齐，按现有采样比例收集点位。
2. `_match_pois()` 统一分派整图及手动局部识别。CNN 从原生地图坐标裁取 64×64 RGB，边界补黑，转换 float32 NCHW、像素除以 255，所有待识别点一次批量推理。
3. 检测器延迟创建并复用 ONNX Runtime CPU session，配置 intra-op=2、inter-op=1，模型为 `data/poi_cnn/epoch-42.onnx`（约 192 KiB，动态 batch、opset 17）。
4. 两个输出头分别做 softmax；建筑 15 类、角标 12 类，下标 0 分别表示无建筑、无角标。建筑视觉变体的概率相加后，从该点位允许的建筑集合中选择最高者，再在该点位该建筑允许的角标集合中选择最高者。共享图标与角标的类型用最小类型编号代表，候选地图评分沿用已有图标/角标等价规则。
5. 手动筛选中指定单点时走同一入口（batch=1），同时保留 `_match_poi()` 单点兼容入口。模板匹配算法保留原有实现。

类别映射来自原训练目录 `assets/meta.txt`，对应代码见 [`poi_cnn.py`](../src/nightreign_overlay/plugins/map_detect/poi_cnn.py)。训练代码、素材、真实切片、checkpoint 和复现说明归档到 [`tools/poi_cnn/`](../tools/poi_cnn/README.md)，生成的 validation/ckpt 缓存不跟踪。模型作为 package data 随 wheel/PyInstaller 打包。

## 复测

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark_poi.py \
  --output tools/poi_cnn/benchmark-results.json
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture \
  tests/plugins/map_detect/test_poi_cnn.py tests/plugins/map_detect/test_map_detect.py tests/plugins/map_detect/test_map_terrain.py -q
```

对比脚本逐种算法调用生产地形、夜王、对齐、POI 和候选评分流程，固定随机种子 42。默认排除 `207_hide.jpg` 的验收统计，仍保留完整预测；`--exclude-from-acceptance` 不带参数可恢复全部样本验收。JSON 分别给出全样本统计及 `acceptance_*` 统计，并保存模型 SHA-256 和软件版本。

验收测试仅运行最终部署的 ONNX Runtime CPU 推理，不依赖 PyTorch 或训练、导出工具。训练和 ONNX 导出步骤见 [`训练说明`](../tools/poi_cnn/README.md)。

`test_poi_cnn.py` 验证 CPU 单点/批量一致、边界裁切、概率归一化、类别约束、局部识别入口、模板分派以及 14 张验收截图的地图 ID。地图旧版逐像素/评分对照测试已移除；当前地图回归以标注截图和实际部署推理结果为准。

## 2026-10-15 整图部署实测

使用更正后的标签 `16.jpg`（原 `7.jpg`）和 `1187.jpg`（原 `1180.jpg`）。共 15 张截图，按用户确认将高难样本 `207_hide.jpg` 保留报告、排除验收统计，其余 14 张参与验收。标签和排除规则只参与评估，不参与图像识别或候选排序。

| 算法 | 验收地图 ID 正确率 | 验收 POI 误差 ≤10 | 全部样本正确率 | 达标 |
|------|------------------|------------------|---------------|------|
| 模板 | 13/14（92.86%） | 6/14 | 13/15（86.67%） | 否 |
| CNN | 14/14（100%） | 11/14 | 14/15（93.33%） | 是 |

CNN 达到本次约定的验收条件：验收样本地图 ID 全部正确，且超过半数截图的 POI 总误差 ≤10。默认算法为 CNN，仍可选择模板匹配。

| 截图 | 模板预测 ID / POI 误差 | CNN 预测 ID / POI 误差 | 计入验收 |
|------|----------------------|----------------------|---------|
| `1088.jpg` | 1088 / 30 | 1088 / 0 | 是 |
| `1126-1176_hide.jpg` | 1126 / 0 | 1126 / 0 | 是 |
| `1137.jpg` | 1137 / 0 | 1137 / 3 | 是 |
| `1137_2.jpg` | 1137 / 75 | 1137 / 9 | 是 |
| `1158.jpg` | 1158 / 40 | 1158 / 0 | 是 |
| `1187.jpg` | 1180 / 3 | 1187 / 0 | 是 |
| `12.jpg` | 12 / 89 | 12 / 22 | 是 |
| `16.jpg` | 16 / 0 | 16 / 0 | 是 |
| `187.jpg` | 187 / 30 | 187 / 20 | 是 |
| `207_hide.jpg` | 249 / 88 | 249 / 95 | 否 |
| `235.jpg` | 235 / 20 | 235 / 0 | 是 |
| `251_hide.jpg` | 251 / 13 | 251 / 13 | 是 |
| `262.jpg` | 262 / 16 | 262 / 6 | 是 |
| `273.jpg` | 273 / 0 | 273 / 3 | 是 |
| `3.jpg` | 3 / 10 | 3 / 10 | 是 |

表中误差是首选候选的生产加权误差，不是错误点位数量。`207_hide.jpg` 两种算法均预测为 249，模板/CNN 的首选误差分别为 88/95，标注地图 207 自身的误差分别为 142/117；完整保留在 JSON 中，不将其包装成识别成功。低候选误差不保证地图 ID 正确。

CNN 的 `12.jpg`、`187.jpg`、`251_hide.jpg` 的误差分别为 22、20、13，其余验收截图误差 ≤10。以上结果仅代表这组固定截图，不保证所有实机截图均达到相同准确率。

逐图机器可读结果：[`benchmark-results.json`](../tools/poi_cnn/benchmark-results.json)。耗时包含预处理、候选评分与诊断写盘，首张包含模型冷启动，不等同于纯 CNN 推理耗时。
