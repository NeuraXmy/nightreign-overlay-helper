# POI CNN 部署与验收

地图识别通过 `poi_algorithm` 配置选择算法：`cnn`（默认）或 `template`，设置页显示名称为“CNN”和“模板匹配”。运行时使用 `onnxruntime`，不依赖 PyTorch、ONNX 导出工具或训练代码。

## 识别流程

1. 沿用地形、夜王检测与 750×750 地图对齐，按现有采样比例收集点位。
2. `_match_pois()` 统一分派整图及手动局部识别。CNN 从原生地图坐标裁取 64×64 RGB，边界补黑，转换 float32 NCHW、像素除以 255，所有待识别点一次批量推理。
3. 检测器延迟创建并复用 ONNX Runtime CPU session，配置 intra-op=2、inter-op=1，模型为 `data/poi_cnn/epoch-42.onnx`（约 192 KiB，动态 batch、opset 17）。
4. 两个输出头分别做 softmax；建筑 15 类、角标 12 类，下标 0 分别表示无建筑、无角标。建筑视觉变体的概率相加后，从该点位允许的建筑集合中选择最高者，再在该点位该建筑允许的角标集合中选择最高者。共享图标与角标的类型用最小类型编号代表，候选地图评分沿用已有图标/角标等价规则。
5. 手动筛选中指定单点时走同一入口（batch=1），同时保留 `_match_poi()` 单点兼容入口。模板匹配算法保留原有实现。

类别映射来自原训练目录 `assets/meta.txt`，对应代码见 [`poi_cnn.py`](../../../src/nightreign_overlay/plugins/map_detect/poi_cnn.py)。训练代码、素材、真实切片、checkpoint 和复现说明归档到 [`tools/poi_cnn/`](../../../tools/poi_cnn/README.md)，生成的 validation/ckpt 缓存不跟踪。模型作为 package data 随 wheel/PyInstaller 打包。

## 复测

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python benchmark/benchmark_poi.py \
  --output tools/poi_cnn/benchmark-results.json
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture \
  tests/plugins/map_detect/test_poi_cnn.py tests/plugins/map_detect/test_map_detect.py tests/plugins/map_detect/test_map_terrain.py -q
```

对比脚本逐种算法调用生产地形、夜王、对齐、POI 和候选评分流程，固定随机种子 42。默认排除 `207_hide.jpg` 的验收统计，仍保留完整预测；`--exclude-from-acceptance` 不带参数可恢复全部样本验收。JSON 分别给出全样本统计及 `acceptance_*` 统计，并保存模型 SHA-256 和软件版本。

验收测试仅运行最终部署的 ONNX Runtime CPU 推理，不依赖 PyTorch 或训练、导出工具。训练和 ONNX 导出步骤见 [`训练说明`](../../../tools/poi_cnn/README.md)。

`test_poi_cnn.py` 验证 CPU 单点/批量一致、边界裁切、概率归一化、类别约束、局部识别入口、模板分派以及 14 张验收截图的地图 ID。地图回归以标注截图和实际部署推理结果为准。

## 固定样本验收

2026-10-15 的模型与模板逐图对照、排除样本和误差定义见[部署评估记录](../../development/experiments/map/poi-cnn-2026-10-15.md)。14 张参与验收的截图仅代表固定样本回归，不能作为所有实机场景的准确率保证。

[返回功能索引](../README.md)
