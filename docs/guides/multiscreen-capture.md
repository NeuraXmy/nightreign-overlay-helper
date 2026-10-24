# 多屏截图与 DPI 验证

## 平台支持与验证范围

默认“自动 (Maa)”始终使用 MaaWin32Screencap。Windows 游戏窗口未打开或句柄失效时，自动模式只等待后续连接，不回退到 mss；macOS 开发应显式选择“兼容 (mss)”。固定 Maa 方法和截图进程选择仅适用于 Windows。

截图、标定、预览与悬浮窗共享设备像素坐标约定。Windows 使用物理桌面原点或客户区原点；macOS 逐屏抓取原生像素后合成共享帧。

| 平台／模式 | 当前行为 | 已完成验证 | 尚需实机确认 |
|---|---|---|---|
| Windows 兼容 (mss) | mss 虚拟桌面整帧，按物理桌面原点裁剪 | 合成多屏、负坐标、混合 DPI、像素内容 | Windows 显卡／桌面实际输出 |
| Windows 仅前台 | DLL 前台掩码，客户区图像转换到物理桌面坐标 | 方法掩码、客户区偏移、尺寸归一化、窗口移动／缩放、线程 DPI 上下文恢复 | DXGI／SCREENDC 实际客户区内容及不同显卡行为 |
| Windows 仅后台 | DLL 后台掩码，同样使用物理客户区坐标 | 与前台相同的坐标测试 | FRAMEPOOL／PRINTWINDOW 实际输出、窗口被遮挡／最小化行为 |
| macOS 兼容 (mss) | 逐屏 mss 原生像素合成 | 合成多屏、Retina 混合缩放、标定／预览／地图叠加 | 实际显示器与录屏权限下的截图 |

目前完成的是合成数据自动回归，尚未完成 macOS 和 Windows 多显示器实机验收。合成测试通过不代表实际桌面、录屏权限和显卡组合均已验证；实机验证步骤见下文。

## 坐标约定与兼容性

截图通过共享 `FrameCaptured.image` 发布，`crop_rgb()` 接收标定区域并根据 `QImage.offset()` 裁剪。所有抓取在专用线程执行。

Windows 保留既有约定：标定区域 = 本屏局部逻辑坐标 × 本屏 DPR + Windows 物理桌面原点。

macOS 使用以下约定，保持每块屏幕的像素原样而不重采样：

```text
屏幕在共享图像中的原点 = 屏幕逻辑原点 × 桌面最大 DPR
标定区域原点 = 屏幕在共享图像中的原点 + 本屏局部逻辑坐标 × 本屏 DPR
标定区域尺寸 = 局部逻辑尺寸 × 本屏 DPR
```

屏幕位置预留的间距可能形成黑色空隙。这是共享图像中的空白区域，屏幕自身的内容和分辨率不变。单屏走直接返回路径，避免额外合成。

标定选择器仍只覆盖开始选择时鼠标所在的屏幕，不支持一次框选跨越两块显示器。原点、缩放或显示器布局变化后需要重新标定。从仅支持 macOS 主屏截图的早期版本升级时，需重新标定副屏区域。

mss 缓存显示器列表；接入／移除屏幕或更改排列、缩放之后，建议重启程序再标定，避免使用旧的显示器布局。

## 自动回归

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:capture \
  tests/plugins/test_capture_multiscreen.py \
  tests/plugins/test_capture_backends.py \
  tests/plugins/test_region_preview.py -q
```

`test_capture_multiscreen.py` 共 70 项：

- 40 项 mss 多屏像素测试：Windows／macOS × 副屏四个方向 × 五组主副屏 DPR `(1,1)`、`(2,1)`、`(1,2)`、`(1.25,1.5)`、`(1.75,2)`。校验图像原点、裁剪内容、尺寸、屏幕选择和预览坐标。
- 20 项 DLL 测试：两种模式 × 100%、125%、150%、175%、200% × 正负窗口位置；同时验证连续帧窗口移动、抓取期间移动的丢帧重试。
- 2 项原生客户区查询测试：成功和失败都恢复线程 DPI 上下文。
- 1 项 macOS 兼容模式路由测试：显式选择 mss 后使用多屏 mss。
- 4 项选择器测试：Windows／macOS 上从选择器保存到预览及地图叠加的坐标一致性。
- 1 项无显示器测试：明确报告失败。

`test_capture_diagnostic.py` 另有 2 项测试，覆盖三种 Windows 模式的 queued 线程抓取、输出文件和失败报告。

测试替换原生取图和 Win32 API，运行生产后端的图像构造、坐标转换和裁剪代码。它们无法覆盖驱动、DLL 内部裁剪或操作系统录屏权限。

## 固定画面截图验证

在 Windows 桌面会话中运行以下工具，可用固定 Qt 画面验证各截图后端的像素准确性并统计耗时：

```powershell
.venv\Scripts\python.exe tools\test_capture_methods.py --layout all
```

工具依次测试普通窗口和无边框全屏，并覆盖 `mss`、`auto` 及各个 Maa 方法。详细结果写入 `.tmp/capture-methods/report.json`。该工具需要真实 Windows 桌面、Qt 显示会话和 `src/nightreign_overlay/plugins/native/MaaWin32Screencap.dll`，不适合在无头环境或普通 pytest 中运行。
## 实机诊断工具

使用应用运行环境执行 `tools/diagnose_capture.py`。脚本经生产 `_CaptureWorker` 及 Qt queued 信号在独立线程抓取，不修改用户配置，不切换失败的截图模式。

输出目录包含：

- `report.json`：Qt／mss 显示器布局、DPR、每种模式的成败、帧尺寸和原点、可选色块校验及区域裁剪尺寸。
- `capture.log`：后端选择日志和失败堆栈，包括 DLL 实际选择的方法。
- `auto.png`、`foreground.png`、`background.png`：各模式截图。
- 指定 `--region X Y W H` 时，额外保存各模式的 `*-region.png`。

退出码 0 表示请求的截图、保存和可选校验成功，1 表示存在失败。原生抓取超时且线程不能退出时，会先保存报告，再以退出码 2 终止独立诊断进程。

### macOS

在具有屏幕录制权限的终端执行：

```bash
.venv/bin/python tools/diagnose_capture.py --mode all --markers \
  --output .tmp/capture-macos
```

`--markers` 会在每块屏幕中心短暂显示一个色块，并检查截图对应区域的颜色。此测试先在普通桌面／窗口模式下执行；独占全屏、其他置顶窗口、HDR／颜色管理及录屏权限可能影响色块可见性或颜色，色块失败需结合截图判断原因。

请至少覆盖主屏与副屏分别为游戏所在屏幕，以及 Retina 主屏 + 普通副屏、普通主屏 + Retina 副屏。macOS 的“兼容 (mss)”模式应覆盖所有显示器。

### Windows

如需验证兼容模式的整个桌面多屏定位，显式指定 `mss`：

```powershell
.venv\Scripts\python.exe tools\diagnose_capture.py --mode mss --markers --output .tmp\capture-windows-desktop
```

启动游戏后，在每块屏幕上分别运行 Maa 模式：

```powershell
.venv\Scripts\python.exe tools\diagnose_capture.py --mode all --output .tmp\capture-windows-game
```

也可以从程序的已标定区域状态中读取 `X Y W H`，追加 `--region X Y W H`，检查三种截图方式裁出的游戏内容是否一致。DLL 抓客户区，整帧尺寸小于桌面是正常行为，比较的是相同全局区域的内容。

Windows DLL 客户区截图可能不包含独立色块窗口，因此脚本仅对 Windows 兼容 (mss) 模式自动校验色块。DLL 的验收依据为游戏截图、区域裁剪以及日志中的实际方法。

推荐实机矩阵：

| 维度 | 测试组合 |
|---|---|
| 显示器位置 | 副屏在右／左／上，包含负坐标 |
| 缩放 | 同为 100%；100% + 150%；125% + 200%；交换主副屏缩放 |
| 游戏位置 | 主屏、副屏；窗口移动后重新标定 |
| 游戏显示 | 普通窗口、无边框全屏；独占全屏单独记录 |
| 后台状态 | 正常显示、被其他窗口遮挡、最小化，逐一记录仅后台的实际行为 |

移动游戏、更换显示器布局或缩放后，先重启程序并重新标定，再判断截图识别是否正常。对于每次测试，使用不同的 `--output` 路径保存报告，避免覆盖前一组结果。

[返回指南索引](README.md)
