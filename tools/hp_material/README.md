# HP 材质与端帽模型

这是离线训练工具。应用直接使用随包分发的两个 ONNX 模型，复用现有 `onnxruntime`，不会安装或调用 scikit-learn。

在仓库根目录准备环境：

```powershell
uv pip install --python .venv/Scripts/python.exe -r tools/hp_material/requirements.txt
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONPATH='.;src'
python tools/hp_material/train.py --context-augmentation --output .tmp/hp_model
python -m tests.support.hp_production_evaluation --model-dir .tmp/hp_model --output .tmp/hp_model_report.json
```

数据取自 `tests/data/hp_detect/videos/production_annotations.json`，首先验证 fixture 哈希，再取稳定标注区间每八帧训练。标签为人工可用端点 U、原外框端点 T 所定义的可用槽体／灰段／背景，以及 U、T 附近的端帽正例。训练集没有视频 ID、坐标、帧号或恒定长度标志特征。端点上下各一像素的标签含抗锯齿容差，边界附近不参与材质像素分类训练。

模型以左侧填充和条外邻域归一化纵向外观，材质特征 72 维；端帽特征取候选左右五个局部采样，共 360 维。模型参数和随机种子在 `train.py`。输出 `training.json` 保存来源哈希、逐录像训练帧号、类别、特征版本和模型文件哈希。导出器可能生成不同内部节点名称，不应以两次 ONNX 字节完全相同代替预测一致性检查。

`--context-augmentation` 增加底部两行上下文不足时的反射版本，用于裁剪边缘的鲁棒性；打包模型使用此选项。归一化与特征实现直接导入生产模块，避免训练／推理漂移。输出模型须先完成联合回归再替换 `src/nightreign_overlay/plugins/hp_marker/data/`，并同时保存对应 `training.json`。PyInstaller 的现有包资源收集规则会包含这些模型。

可复现的时间块留出：

```powershell
python tools/hp_material/train.py --context-augmentation --holdout-blocks --output .tmp/hp_holdout
python -m tests.support.hp_production_evaluation --model-dir .tmp/hp_holdout --heldout-blocks-only --skip-starts --output .tmp/hp_holdout_report.json
```

训练仅包含 0–5、10–15 等交替五秒块，评分只包含 5–10、15–20 等留出块与稳定 GT 区间的交集。忽略评分的帧仍按正常顺序输入检测器，模型看不到 GT。评估命令核对训练元数据，拒绝将全数据训练模型伪装成留出验证。该划分仍来自相同源录像，不能替代录像级独立验证；`--exclude-video <id>` 可进行整段录像留出实验。

打包模型的四段回归全部达标，但独立时间块下仍有罕见特效误报。当前结论与完整数值见 [算法文档](../../docs/HP_MATERIAL_DETECTION.md)，不要将四段同集成绩表述为新录像的泛化保证。
