# Corresponding source / 对应源码

## 中文

对应源码作为独立的 `<版本>-sources.zip` 附件免费提供，位于程序 ZIP 所在的同一个 GitHub Release：
https://github.com/NeuraXmy/nightreign-overlay-helper/releases

请下载与程序版本相同的源码附件。程序目录的 `licenses/source-manifest.json` 记录项目提交、
依赖版本及源码归档 SHA-256，可与源码附件内的 `manifest.json` 核对。
本地构建会在 `dist/` 中并列生成程序 ZIP 和源码 ZIP；源码不会放进程序目录。
转发程序时请保留许可证、版权声明、本说明，并同时提供对应源码的明确下载入口。

源码附件包含项目的精确 Git 源码快照、PyQt6 和 PyQt6-Fluent-Widgets 的匹配 sdist、
Fluent Widgets 固定提交的可编辑 Qt 资源，以及清单。项目未修改上述两个依赖。

构建主程序：解压项目源码，在 Windows x64 安装 Git、uv 和 .NET 8 SDK，
从干净 Git 工作区运行 `build.bat`。源码 ZIP 不含 `.git`，可先运行 `git init`、
`git add .` 和 `git commit` 创建本地快照再构建；新提交 SHA 与原发布不同。
脚本使用 Python 3.13 与锁定依赖。详情见源码中的 `docs/development/releases/README.md`。

构建 PyQt6：按 sdist 内 README 和 `pyproject.toml` 的 SIP 配置准备匹配的 Qt 开发环境。
Fluent Widgets 1.11.3 使用 setuptools，可通过 `python -m pip wheel --no-deps .` 构建。
上游地址及许可见 `licenses/THIRD-PARTY-NOTICES.md`。

上述材料覆盖项目和这两个 GPL 依赖；Qt、.NET 及其他依赖的许可与源码要求需分别核对。

## English

Corresponding source is available free of charge as a separate `<version>-sources.zip`
attachment in the same GitHub Release as the Windows runtime ZIP:
https://github.com/NeuraXmy/nightreign-overlay-helper/releases

Download the source attachment matching your application version. Compare its `manifest.json`
with `licenses/source-manifest.json` in the runtime folder for the exact application commit,
dependency versions and source archive SHA-256 hashes. Local builds create both ZIPs beside
each other in `dist/`; source archives are not stored in the runtime folder.
When redistributing, preserve licenses, copyright notices and this document, and provide
clear access to the matching corresponding source.

The source attachment contains the exact application Git snapshot, matching PyQt6 and
PyQt6-Fluent-Widgets sdists, a pinned Fluent Widgets repository archive with editable Qt
resources, and the manifest. These two dependencies are used without local modifications.

To build the application, install Git, uv and .NET 8 SDK on Windows x64 and run `build.bat`
from a clean Git worktree. The source snapshot has no `.git`; initialize and commit a local
repository first when building from the ZIP. This creates a different commit SHA. The build
uses Python 3.13 and locked dependencies. See `docs/development/releases/README.md`.

To build PyQt6, follow its README and SIP configuration with a matching Qt development
environment. Fluent Widgets 1.11.3 uses setuptools: `python -m pip wheel --no-deps .`.
See `licenses/THIRD-PARTY-NOTICES.md` for upstream locations and license details.
These materials cover the application and the two named GPL dependencies; other runtimes,
including Qt and .NET, have separate notice and source requirements.
