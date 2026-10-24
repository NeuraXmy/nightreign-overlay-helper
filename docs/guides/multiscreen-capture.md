# 多屏截图与 DPI 验证

## 平台支持与验证范围

截图、标定、预览与悬浮窗共享设备像素坐标约定。Windows 由 MaaWin32Screencap DLL 抓取游戏窗口客户区，并转换到物理桌面坐标；截图仅支持 Windows，其他平台的请求会失败并限频告警。

| 平台／方式 | 当前行为 | 已完成验证 | 尚需实机确认 |
|---|---|---|---|
| Windows auto／前台／后台 | DLL 测速或按掩码选择方式，客户区图像转换到物理桌面坐标 | 方法掩码、客户区偏移、尺寸归一化、窗口移动／缩放、线程 DPI 上下文恢复 | DXGI／SCREENDC 实际客户区内容及不同显卡行为 |
| Windows 固定单一方式 | `gdi`…`screendc` 单一方式位掩码，不再自动测速 | 键值映射、固定进程的窗口解析 | 各方式实际输出与兼容性 |
| 非 Windows | 无后端，请求失败并限频告警 | 失败路径 | — |

目前完成的是合成数据自动回归，尚未完成 Windows 多显示器实机验收。合成测试通过不代表实际桌面和显卡组合均已验证；实机验证步骤见下文。

## 坐标约定与兼容性

截图通过共享 `FrameCaptured.image` 发布，`crop_rgb()` 接收标定区域并根据 `QImage.offset()` 裁剪。所有抓取在专用线程执行。

Windows 保留既有约定：标定区域 = 本屏局部逻辑坐标 × 本屏 DPR + Windows 物理桌面原点。

屏幕原点按桌面最大 DPR 放置，屏内坐标按本屏 DPR 缩放；`core/screens.py` 统一标定、预览和地图/血条悬浮窗的转换。

标定选择器仍只覆盖开始选择时鼠标所在的屏幕，不支持一次框选跨越两块显示器。原点、缩放或显示器布局变化后需要重新标定。

接入／移除屏幕或更改排列、缩放之后，建议重启程序再标定，避免使用旧的显示器布局。

## 自动回归

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture \
  tests/plugins/test_capture_multiscreen.py \
  tests/plugins/test_capture_backends.py \
  tests/plugins/test_region_preview.py -q
```

`test_capture_multiscreen.py`：

- DLL 测试：auto／前台／后台／固定 GDI × 100%、125%、150%、175%、200% × 正负窗口位置；同时验证连续帧窗口移动、抓取期间移动的丢帧重试。
- 2 项原生客户区查询测试：成功和失败都恢复线程 DPI 上下文。
- 1 项非 Windows 失败路径测试：明确抛错并限频告警。
- 4 项选择器测试：Windows／macOS 上从选择器保存到预览及地图叠加的坐标一致性。

`test_capture_diagnostic.py` 另有 2 项测试，覆盖全部截图方式的 queued 线程抓取、输出文件和失败报告。

测试替换原生取图和 Win32 API，运行生产后端的图像构造、坐标转换和裁剪代码。它们无法覆盖驱动、DLL 内部裁剪或操作系统录屏权限。

## 实机诊断工具

使用应用运行环境执行 `tools/diagnose_capture.py`。脚本经生产 `_CaptureWorker` 及 Qt queued 信号在独立线程抓取，不修改用户配置，不切换失败的截图方式。

输出目录包含：

- `report.json`：Qt 显示器布局、DPR、每种方式的成败、帧尺寸和原点及区域裁剪尺寸。
- `capture.log`：后端选择日志和失败堆栈，包括 DLL 实际选择的方法。
- 各方式截图 `auto.png`、`foreground.png`、`background.png`、`gdi.png` 等。
- 指定 `--region X Y W H` 时，额外保存各方式的 `*-region.png`。

退出码 0 表示请求的截图、保存和可选校验成功，1 表示存在失败。原生抓取超时且线程不能退出时，会先保存报告，再以退出码 2 终止独立诊断进程。

### Windows

启动游戏后，在每块屏幕上分别运行全部方式：

```powershell
.venv\Scripts\python.exe tools\diagnose_capture.py --mode all --output .tmp\capture-windows-game
```

也可以从程序的已标定区域状态中读取 `X Y W H`，追加 `--region X Y W H`，检查各截图方式裁出的游戏内容是否一致。DLL 抓客户区，整帧尺寸小于桌面是正常行为，比较的是相同全局区域的内容。

Windows DLL 客户区截图可能不包含独立色块窗口，验收依据为游戏截图、区域裁剪以及日志中的实际方法。

推荐实机矩阵：

| 维度 | 测试组合 |
|---|---|
| 显示器位置 | 副屏在右／左／上，包含负坐标 |
| 缩放 | 同为 100%；100% + 150%；125% + 200%；交换主副屏缩放 |
| 游戏位置 | 主屏、副屏；窗口移动后重新标定 |
| 游戏显示 | 普通窗口、无边框全屏；独占全屏单独记录 |
| 后台状态 | 正常显示、被其他窗口遮挡、最小化，逐一记录仅后台的实际行为 |
| 固定方式 | GDI／PrintWindow／DXGI／FramePool 逐一固定并与 auto 结果对比 |
| 串流游玩 | PS5 串流等场景固定截图进程后验证各方式 |

移动游戏、更换显示器布局或缩放后，先重启程序并重新标定，再判断截图识别是否正常。对于每次测试，使用不同的 `--output` 路径保存报告，避免覆盖前一组结果。

[返回指南索引](README.md)
