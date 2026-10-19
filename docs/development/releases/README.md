# 发布指南与记录

本页说明当前 Windows x64 构建流程与验收要求。历史审计放在独立文件中，避免将已修复问题当作当前缺陷。

## 发布记录

| 日期 | 审计快照 | 后续处理 |
| --- | --- | --- |
| 2026-10-19 | [22 项问题与风险](2026-10-19-audit.md) | [18 项修复及验证范围](2026-10-19-fixes.md)；A14、A16、A18、A19 按维护决定保留 |

## Windows 文件夹构建

在 Windows x64 上安装 `uv` 与 .NET 8 SDK，并确保它们已加入 `PATH`，然后运行项目根目录的：

```bat
build.bat
```

脚本从自身所在目录执行，使用 Python 3.13（由 `uv` 管理），按纳入版本管理的 `uv.lock` 锁定同步 `build` 依赖组，
构建 Steam/ETW 辅助程序，再通过 `nightreign-overlay-helper.spec` 构建主程序。
首次构建需要联网下载 Python、Python 依赖与 NuGet 包。自动化环境可设置 `CI=1` 跳过结束时的暂停。

输出为完整文件夹，而非单个 EXE：

```text
dist/nightreign-overlay-helper/
├── nightreign-overlay-helper.exe
├── _internal/                 # Python、Qt、第三方库、核心与插件资源、截图 DLL
├── bin/                       # 联机辅助 EXE、.NET 运行库、Steam/ETW 依赖
├── third-party/               # 联机组件的第三方声明与许可证
├── LICENSE
└── README.md
```

运行 `nightreign-overlay-helper.exe` 即可；发布、移动或压缩分发时须保留整个文件夹，
不能只复制 EXE。主程序采用 PyInstaller `onedir`，联机辅助程序也采用自包含多文件发布，
启动时不需要将内嵌运行库解压到临时目录，用户无需安装 Python 或 .NET。
设置、日志与缓存仍写入用户数据目录，不写入 `_internal`。

截图 DLL 位于 `src/nightreign_overlay/plugins/capture/native/`。
spec 自动收集各插件的翻译、教程、图片、模板、CSV 与字体，
并处理 Qt VC 运行库收集和 OpenCV／Qt ICU 冲突过滤。
Windows EXE 必须在 Windows 上构建；macOS 开发环境不能直接生成该产物。

### GitHub Actions 自动构建

[`Build Windows ZIP`](../../../.github/workflows/build-windows.yml) 在 Windows x64 runner 上复用
`build.bat`，使用 Python 3.13 与 .NET 8 SDK，构建完成后将整个发布目录打包为 ZIP。

- 手动构建：进入仓库 **Actions → Build Windows ZIP → Run workflow**，选择需要构建的分支或 tag。
- 版本构建：推送版本 tag 自动触发，支持 `v1.0.0`、`1.0.0` 等命名，也支持带版本后缀的 tag。
- 下载：在成功的 workflow 运行页面的 **Artifacts** 中下载产物，内含最终分发用 ZIP；保留时间为 30 天。

tag 构建的 ZIP 名称例如 `nightreign-overlay-helper-v1.0.0-windows-x64.zip`；
手动构建以 `manual-dev` 标记，名称包含提交短 SHA 与运行编号。解压后保留完整的 `nightreign-overlay-helper/` 文件夹，
运行其中的 EXE。CI 在打包前运行完整 pytest、Ruff 检查及格式检查，并通过
`scripts/check_runtime_resources.py` 实际加载和推理 POI、血条材质与端帽模型，检查内置插件发现和加载。
打包后检查主程序、截图 DLL、三个 ONNX 模型、联机辅助程序、ETW DLL 和许可证是否齐全。
版本 tag 必须与 `src/nightreign_overlay/__init__.py` 的版本一致；支持可选 `v` 前缀和
`1.0.0-dev.2`／`1.0.0.dev2` 等 PEP 440 等价预发布写法。不一致时构建失败。
分发 EXE 的真实启动、Steam/ETW 与截图设备行为仍需在 Windows 发布验收中确认。
workflow 文件需存在于所构建的 tag 中；GitHub 的手动运行入口需要该 workflow 先进入默认分支。

## 发布前验证

本地 `build.bat` 负责构建，不代替测试；发布 CI 在构建前执行完整 pytest、Ruff、运行资源推理和插件发现检查。开发环境可从仓库根目录运行：

```bash
uv sync --locked --dev --group build
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_runtime_resources.py
git diff --check
```

版本以 `src/nightreign_overlay/__init__.py` 为准。推送 tag 前，使用实际计划的 tag 执行 `uv run python scripts/validate_release_version.py <tag>`；尖括号表示需要替换的值。

在目标 Windows 环境检查最终 ZIP 解压后的真实启动、UAC、首次配置与重启、全部功能启停、截图 DLL、输入设备、Steam／ETW、HDR 和多屏。保留验收环境、产物版本、未验证项与已接受限制；自动测试与 macOS 调试结果不能代替这些检查。

联机辅助程序的单独构建与路径规则见[联机状态](../../features/p2p.md)，多屏诊断步骤见[多屏截图与 DPI](../../guides/multiscreen-capture.md)。

[返回开发维护](../README.md)
