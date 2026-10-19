# Corresponding source / 对应源码

## 中文

完整 Windows 发布文件夹的 `source/` 包含：

- `nightreign-overlay-helper-source.zip`：构建该程序的 Git 提交源码，含
  `uv.lock`、Python 与 C# 源码、资源及构建脚本。
- PyQt6 和 PyQt6-Fluent-Widgets 的原始源码发行包（sdist），版本与本次
  构建环境和 `uv.lock` 一致。本项目未修改这两个依赖。
- Fluent Widgets 的固定上游提交 ZIP：补齐 sdist 中未提供的可编辑 Qt
  资源（QRC、图片与样式等）。构建时逐一核对其中 Python 源码与 sdist 一致。
- `manifest.json`：项目提交 SHA、依赖版本、原始下载 URL 和各源码归档的
  SHA-256。下载时对照锁文件校验，打包前再次校验归档。

源码与二进制放在同一个发布包内，无须另行申请或付费。分发时保留整个
`source/`、`licenses/`、`third-party/`、`LICENSE` 及本文件；不要只分享 EXE。
也可从 https://github.com/NeuraXmy/nightreign-overlay-helper 获取项目源码，
并按 `manifest.json` 中的提交定位。仓库默认分支可能已不同于本次发布。

构建主程序：解压项目源码，在 Windows x64 安装 Git、uv 和 .NET 8 SDK，
从对应 Git 提交的干净工作区运行 `build.bat`。源码 ZIP 没有 `.git`：可先
用 `git init`、`git add .` 和 `git commit` 创建本地源码快照再构建；本地提交
SHA 会不同于原发布。脚本使用 Python 3.13、锁定依赖并下载上述依赖源码。
详情见源码中的 `docs/development/releases/README.md`。

构建 PyQt6：解压对应 sdist，按包内 README 和 `pyproject.toml` 的 SIP 构建
说明安装构建依赖，并提供匹配的 Qt 开发环境。Fluent Widgets 1.11.3 的 sdist 使用 `setup.py`
和 setuptools，可通过 `python -m pip wheel --no-deps .` 构建。它们的上游地址和完整许可见
`licenses/THIRD-PARTY-NOTICES.md`。

这些源码归档覆盖本项目和上述两个 GPL 依赖，不代表其他打包运行库的
许可证或源码义务已全部审计。Qt、.NET 及其他依赖应分别保留适用声明、
按各自许可提供所需材料。

## English

The complete Windows release includes `source/` containing the application's
exact Git source snapshot (`nightreign-overlay-helper-source.zip`), the original
PyQt6 and PyQt6-Fluent-Widgets source distributions, and `manifest.json`.
A pinned Fluent Widgets repository ZIP also preserves editable Qt resources
(QRC, images and styles) missing from its sdist. The build compares all package
Python sources, including generated resource code, against the sdist.
The manifest records the application commit, dependency versions, upstream URLs
and SHA-256 hashes. Both dependencies are used without local modifications.
The build checks their versions against `uv.lock` and verifies downloaded hashes.

Source is included alongside the binaries at no additional charge. Preserve
`source/`, `licenses/`, `third-party/`, `LICENSE` and this file when redistributing.
The project repository is https://github.com/NeuraXmy/nightreign-overlay-helper;
use the manifest's commit rather than assuming the default branch matches.

To build the application, install Git, uv and .NET 8 SDK on Windows x64 and run
`build.bat` from a clean checkout of the recorded commit. The script uses Python
3.13, locked dependencies and downloads the dependency source archives. The
source ZIP has no `.git`; initialize and commit a local Git repository first
if building directly from that ZIP. Its new local commit will differ from the
original release commit. See `docs/development/releases/README.md` in the source.

To build PyQt6, follow the README and SIP build configuration in its source
archive, using a matching Qt development environment. Fluent Widgets 1.11.3 uses
`setup.py` and setuptools; build its source archive with `python -m pip wheel --no-deps .`. Upstream links and full license notices
are in `licenses/THIRD-PARTY-NOTICES.md`.

These archives cover the application and the two named GPL dependencies. Other
bundled runtimes, including Qt and .NET, have separate notice/source requirements;
this document does not certify a complete dependency audit.
