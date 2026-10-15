# POI CNN 训练与 ONNX 导出

以下命令均在仓库根目录执行，使用 Python 3.11 或更新版本。

## 安装训练与导出依赖

```bash
python -m pip install -r tools/poi_cnn/requirements.txt
```

## 数据与模型

- `assets/`：建筑、角标、背景、玩家标记及干扰图案；建筑类别说明见 [`assets/meta.txt`](assets/meta.txt)。
- `synthesize.py`：使用上述素材合成样本，并进行缩放、位置扰动、颜色和画质增强。
- `testset/`：真实 POI 切片与 `labels.jsonl`，用于训练过程中的模型选择。
- `train.py`：定义四层卷积、双输出头模型 `PoiNet`，以及训练与验证流程。

模型输入为 64×64 RGB 切片，使用 float32、NCHW 格式，像素值除以 255，不使用其他标准化。两个输出头分别输出 15 类建筑和 12 类角标的 logits；下标 0 分别表示无建筑、无角标，素材文件编号从 `00.png` 开始，对应输出下标 1。

## 训练

使用 CUDA 训练：

```bash
python tools/poi_cnn/train.py --device cuda --workers 8 --epochs 50 \
  --output tools/poi_cnn/ckpt/poi_net.pt
```

没有 CUDA 时会自动回退 CPU，也可以显式指定 CPU：

```bash
python tools/poi_cnn/train.py --device cpu --workers 0 --epochs 50 \
  --output tools/poi_cnn/ckpt/poi_net.pt
```

常用参数：

| 参数 | 默认值 | 作用 |
|------|--------|------|
| `--steps` | 1000 | 每轮训练的 batch 数 |
| `--batch-size` | 128 | 每个训练 batch 的样本数 |
| `--val-size` | 500 | 合成验证集样本数 |
| `--patience` | 10 | 连续未改善多少轮后提前停止，0 表示禁用 |
| `--min-delta` | 0.0001 | 模型选择指标的最小改善幅度 |

训练样本实时合成，合成验证集在每次启动时重新生成。默认使用真实切片集的建筑准确率与角标准确率之和选择最佳模型，因此 `testset/` 属于模型选择集，不能作为独立泛化测试集。

上述命令在 `tools/poi_cnn/ckpt/` 下生成最佳模型 `poi_net.pt`、每轮权重 `epoch-N.pt` 和训练曲线 `curves.png`。生成的 `validation/` 和 `ckpt/` 目录由 Git 忽略。

仓库提供的 `epoch-42.pt` 可直接用于导出。训练过程未固定全部随机源，重新训练可以复现流程，但不保证得到完全相同的权重。

## 导出 ONNX

导出仓库提供的权重：

```bash
python tools/poi_cnn/export.py
```

默认读取 `tools/poi_cnn/epoch-42.pt`，输出到 `src/nightreign_overlay/plugins/map_detect/data/poi_cnn/epoch-42.onnx`。

导出自己训练的权重并指定输出位置：

```bash
python tools/poi_cnn/export.py \
  --checkpoint tools/poi_cnn/ckpt/poi_net.pt \
  --output tools/poi_cnn/ckpt/poi_net.onnx
```

导出使用 opset 17，输入名为 `images`，形状为 `[batch, 3, 64, 64]`；输出名为 `base_logits` 和 `corner_logits`，形状分别为 `[batch, 15]` 和 `[batch, 12]`。输入和输出均支持动态 batch。导出完成后，脚本使用 ONNX checker 验证模型结构。
