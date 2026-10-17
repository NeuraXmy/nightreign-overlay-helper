# 日志与调试图片打包

入口位于「关于 → 问题反馈」。弹窗支持填写可选的问题描述、多次选择附加图片，以及移除所选附件。点击「导出 ZIP」后在后台线程打包，完成后显示文件路径和「打开所在目录」按钮，用户自行将 ZIP 附在问题反馈中。

输出路径为 `user_data_dir()/reports/diagnostics_{datetime}.zip`，时间精确至微秒。导出仅生成本地文件，不会自动上传。

## 压缩包内容

| 路径 | 内容 |
|---|---|
| `problem.txt` | UTF-8 问题描述，未填写时为空 |
| `logs/` | 用户数据目录中的现有日志，包括轮转日志 |
| `debug/` | 当前保留的调试图片与对应 JSON，保留原有子目录结构 |
| `attachments/001_{filename}` | 用户主动选择的图片，原文件内容保持不变，序号避免同名覆盖 |
| `manifest.json` | 应用版本、操作系统、Python 版本、导出时间、文件清单及打包时已被清理的文件清单 |

不自动收集整个用户数据目录，因此设置、缓存、旧导出包不进入 ZIP。图片按原格式保存，避免再次有损编码；JPEG、PNG、WebP、GIF 直接存入 ZIP，其余文件使用 DEFLATE 压缩。文件流式写入，不一次性读取所有日志和图片。

打包开始前刷新日志缓冲。导出基于收集时已有的文件，不暂停检测；期间产生的新图片可能需下次导出才能收集。若自动保留策略在打包过程中删除文件，则跳过该文件，并在完成提示及 `manifest.json` 中记录。若用户主动添加的图片丢失、损坏或无法读取，或输出磁盘写入失败，显示错误并保留输入，允许修改后重试。

先写入同目录临时文件，ZIP 完成后才发布最终文件；失败会清理临时文件并保留原目标文件。打包期间禁用重复提交和关闭弹窗，压缩任务不访问 Qt 控件。日志或调试目录不存在时仍可导出问题描述和附件。目录中的符号链接及指向用户数据目录外的目录链接不自动收集。

「保存调试图片」开关仅控制后续截图保存，不影响导出已有图片。各检测结果的保留策略见 [DEBUG_IMAGES.md](DEBUG_IMAGES.md)。导出包不会自动清理，用户可自行删除 `reports/` 下已发送的 ZIP。

## 实现与验证

- [`core/diagnostics.py`](../src/nightreign_overlay/core/diagnostics.py)：不依赖 UI 的 ZIP 生成逻辑。
- [`ui/components/diagnostic_export.py`](../src/nightreign_overlay/ui/components/diagnostic_export.py)：描述、附件选择及线程池后台导出。
- [`ui/pages/about.py`](../src/nightreign_overlay/ui/pages/about.py)：问题反馈入口。

```bash
python -m pytest tests/core/test_diagnostics.py tests/ui/test_diagnostic_export.py -q
```

回归覆盖真实 ZIP 内容及 CRC、中文描述和同名附件、元数据与图片字节保持、缺少诊断目录、保留策略删除文件、无效附件、写入失败清理，以及界面的后台执行、重复提交保护、失败重试和关于页入口。
