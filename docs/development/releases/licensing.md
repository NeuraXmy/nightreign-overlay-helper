# 许可证与源码分发

项目自有代码采用 AGPL-3.0-only；SteamP2PInfo 采用 MIT；公共发行版
PyQt6-Fluent-Widgets 和 PyQt6 采用 GPLv3。AGPLv3 第 13 条允许与 GPLv3
组件组合，第三方组件保留自身的许可与版权声明。这里记录的是发布材料的
准备与验证方式，不是对全部依赖作出的合规结论。

## 文件与维护位置

- 根目录 `LICENSE`：项目 AGPL 完整文本。
- `src/nightreign_overlay/resources/licenses/`：离线查看器使用的 AGPL、
  两个 GPL 完整文本、SteamP2PInfo MIT 文本、第三方声明与中英文源码说明。
- `native/licenses/` 与 `native/THIRD-PARTY-NOTICES.txt`：联机辅助程序的
  MIT 许可证及声明。查看器中的 SteamP2PInfo 文本必须与此处一致。
- `scripts/prepare_release_licenses.py`：在 Windows 主程序构建后整理
  发布材料，再由 CI 以 `--check` 离线复核。

README 中的链接与“关于 → 许可证与源码”提供入口。查看器离线显示全文，
四种界面语言均有入口、免责和再分发提示；原始法律文本保持英文原文。

## 发布流程

1. 提交所有变更，保持 `git status --porcelain` 为空。构建脚本拒绝脏工作区，
   避免程序来自本地修改、源码却来自旧提交。忽略的构建输出不影响检查。
2. 运行 `build.bat`。脚本核对已安装的两个 GPL 组件版本与 `uv.lock`，
   比较安装包与仓库中的完整许可证文本；不一致时要求维护者审核更新。
3. 脚本通过 `git archive HEAD` 生成项目源码 ZIP；按 `uv.lock` 的 sdist URL
   下载上述两个依赖的原始源码归档并校验 SHA-256。Fluent Widgets 的 sdist
   不含可编辑的 Qt 资源，还要按 `source-origins.json` 下载固定提交的上游 ZIP，
   补齐 QRC、图片和样式，并核对其中全部 Python 源码与 sdist 一致。下载失败或哈希不符时
   构建失败，不回退到上游默认分支或不同版本。
4. 在发布目录生成 `source/manifest.json`，记录 Git 提交、归档名、依赖版本、
   原始 URL 和 SHA-256；复制 `licenses/`、`SOURCE.md` 及辅助程序 MIT 文件。
5. CI 再运行 `uv run --no-sync python scripts/prepare_release_licenses.py --check`，
   检查许可证原文、源码归档哈希、锁定版本与项目提交，然后压缩完整目录。

发布 ZIP 自带这些源码，无须用户另行索取。将发布包上传到 Release 时，应在
下载说明中保留源码随包提供的提示。GitHub Actions 的临时 Artifact 有保留期限，
不能作为长期源码可得性的唯一安排；重新托管或转发二进制时一起保留源码材料。

## 升级与审计边界

更新 PyQt6 或 Fluent Widgets 时，检查对应版本的许可证、版权声明、`source-origins.json` 固定提交和源码
构建说明，必要时更新离线材料。当前声明按未修改的公共发行版准备；若修改
依赖，必须包含修改后的实际源码及变更说明，不能继续只附上游原始 sdist。

Fluent Widgets 随包说明将 GPL 使用描述为 “non-commercial project”，同时
附有标准 GPLv3 文本。声明中保留了这段上游说明和商业授权入口，不擅自给
GPL 增加限制，也不声称购买过商业授权；商业授权范围有疑问时需向权利人确认。

本次材料覆盖项目与上述指定组件。PyQt6 绑定与 Qt 运行库是不同组件；Qt、
PyQt6-sip、其他 Python 包、.NET、原生 DLL、模型与资源仍需分别检查其许可、
版权和可能的源码提供要求。不能把本页或已通过的检查当作所有依赖均已合规。

[返回发布指南](README.md) · [返回文档索引](../../INDEX.md)
