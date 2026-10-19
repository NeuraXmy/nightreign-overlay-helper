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
构建前需要提交所有源码变更，脚本拒绝存在未提交修改或未忽略的新文件的工作区，
保证源码快照与二进制对应。构建需要联网下载 Python、Python 依赖、NuGet 包，以及
锁定版本的 PyQt6 和 Fluent Widgets 源码归档。自动化环境设置 `CI=1` 时跳过结束暂停，并由 workflow 的独立步骤执行 `python -m scripts.package_release` 生成 ZIP，避免重复压缩。

输出包含完整程序文件夹，以及两个独立 ZIP（本地构建名称使用 `manual-dev-<SHA>-local`）：

- `nightreign-overlay-helper-<版本>-windows-x64.zip`：运行所需文件、许可证、源码下载说明与小型版本清单。
- `<版本>-sources.zip`：对应项目源码、两个 GPL 依赖 sdist、Fluent 资源源码和哈希清单。

源码在 `dist/release-sources/` 准备，独立于下列程序目录：

```text
dist/nightreign-overlay-helper/
├── nightreign-overlay-helper.exe
├── _internal/                 # Python、Qt、第三方库、核心与插件资源、截图 DLL
├── bin/                       # 联机辅助 EXE、.NET 运行库、Steam/ETW 依赖
├── third-party/               # 联机组件的第三方声明与许可证
├── licenses/                  # 项目 AGPL、PyQt6 / Fluent Widgets GPL 及版权声明
├── SOURCE.md                  # 对应源码附件下载入口与构建说明
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

### GitHub Actions 构建与发布

[`Build Windows ZIP`](../../../.github/workflows/build-windows.yml) 在 Windows x64 runner 上复用
`build.bat`，使用 Python 3.13 与 .NET 8 SDK，构建完成后分别打包程序和源码 ZIP。
该流程仅支持手动触发，不创建 GitHub Release。

[`Release Windows ZIP`](../../../.github/workflows/release-windows.yml) 在推送版本 tag 时自动执行
同样的检查与 Windows 构建，全部成功后创建对应的 GitHub Release，附加程序和源码两个 ZIP，并自动生成发布说明及源码获取提示。
发布任务单独授予 `contents: write` 权限；构建任务只读仓库内容。

- 手动构建：进入仓库 **Actions → Build Windows ZIP → Run workflow**，选择需要构建的分支或 tag。
- 版本发布：推送版本 tag 触发 **Release Windows ZIP**，支持 `v1.0.0`、`1.0.0` 等命名，也支持带版本后缀的 tag。
- 发布渠道：按应用的 PEP 440 版本识别开发版及 alpha／beta／rc 预发布，标记为 **Pre-release**，不设为 Latest；正式版设为 Latest。
- 发布下载：在仓库 **Releases** 中下载附加的 Windows ZIP；发布失败的工作流可重跑。若对应 Release 已存在，创建步骤会失败，不会覆盖现有发布。
- 下载：在成功的 workflow 运行页面的 **Artifacts** 中分别下载程序或源码产物，避免下载程序时同时下载源码；保留时间为 30 天。

tag 构建的 ZIP 名称例如 `nightreign-overlay-helper-v1.0.0-windows-x64.zip`；
手动构建以 `manual-dev` 标记，名称包含提交短 SHA 与运行编号。解压后保留完整的 `nightreign-overlay-helper/` 文件夹，
运行其中的 EXE。CI 在打包前运行完整 pytest、Ruff 检查及格式检查，并通过
`scripts/check_runtime_resources.py` 实际加载和推理 POI、血条材质与端帽模型，检查内置插件发现和加载。
打包后检查主程序、截图 DLL、三个 ONNX 模型、联机辅助程序、ETW DLL 和许可证是否齐全。
`scripts/prepare_release_licenses.py --check` 还会离线核对完整许可证内容、
独立源码目录的归档 SHA-256、依赖版本和项目提交，并核对程序内清单；任何缺失或不一致都阻止打包。
`scripts/package_release.py` 统一为本地和 CI 生成两个附件，ZIP 使用 Deflate 最高压缩级别 9。
Actions 通过 `upload-artifact@v7` 的 `archive: false` 直接上传这两个 ZIP，保留原文件名，避免下载时出现 ZIP 内再套 ZIP。
发布任务通过上传步骤返回的 artifact ID 下载原始 ZIP，再作为 Release 附件发布。
程序 ZIP 不包含源码归档；源码附件与程序一起发布，用户运行程序只需下载 Windows ZIP。
版本 tag 必须与 `src/nightreign_overlay/__init__.py` 的版本一致；支持可选 `v` 前缀和
`1.0.0-dev.2`／`1.0.0.dev2` 等 PEP 440 等价预发布写法。不一致时构建失败。
分发 EXE 的真实启动、Steam/ETW 与截图设备行为仍需在 Windows 发布验收中确认。
发布 workflow 文件需存在于所推送的 tag 中；旧 tag 不会因本次配置自动重新发布。
GitHub 的手动构建入口需要构建 workflow 先进入默认分支。

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

许可证文件维护、源码准备和审计范围见[许可证与源码分发](licensing.md)。

[返回开发维护](../README.md)
