# 手动发布与三站同步

当 GitHub Actions 无法运行，或需要为已有 Release 补镜像时使用本流程。命令从仓库根目录执行，
示例使用 Windows PowerShell。发布行为以当前检出的 [发布 workflow](../../../.github/workflows/release-windows.yml)、
[Gitee 脚本](../../../scripts/sync_gitee_release.py) 和 [CNB 脚本](../../../scripts/sync_cnb_release.py) 为准；
不要复制旧版本临时脚本后仅修改文件名，也不要重新压缩已发布附件。

## 发布范围与凭据

**手动发布默认覆盖 GitHub、Gitee、CNB，包括开发版；只有用户明确说明不需要时才跳过对应站点。**
当前 tag 自动发布 workflow 仍只自动同步正式版，开发版需按本页补同步。

| 站点 | 附件 | 正文与渠道 |
| --- | --- | --- |
| GitHub | 完整 Windows ZIP、对应源码 ZIP | 使用 `docs/development/releases/<tag>.md`；开发版标记 Pre-release 且不设 Latest |
| Gitee | 程序不超过 50 MiB 时上传原 ZIP，否则上传原始字节分卷及清单 | 上游正文加 `mirror_notes()` 生成的下载说明和源码链接；保留上游预发布标记 |
| CNB | 完整 Windows ZIP | 保留上游标题、正文和预发布标记；预发布 `make_latest=false`，正式版 `legacy` |

Gitee/CNB 不上传源码 ZIP，不推送项目源码或 GitHub 提交历史。对应源码保留在 GitHub 同版本 Release。
开发版标签必须保留 `dev`／`alpha`／`beta`／`rc` 等后缀，不能为镜像改成正式版本号。
当前客户端只接收 `v?数字.数字.数字` 的正式标签，并过滤预发布标记，因此开发版镜像不会触发正式版更新提示。

开始前先在 **`sandbox/` 下寻找凭据文件**，可先只列出文件名，再在进程内读取与本次发布相关的文件。
文件可能使用 `GITEE_TOKEN`／`CNB_TOKEN` 等标记，也可能按服务分段；先确认所属服务，不要猜测。
**找不到所需令牌、所属服务不明确或令牌失效时，询问用户提供本地凭据文件位置；不要要求把令牌粘贴到聊天。**
GitHub 还可以使用已登录的 `gh` 或 Git credential manager 既有凭据。GitHub Actions Secrets 无法反向读取。

将凭据仅加载到当前进程环境：`GH_TOKEN`、`GITEE_TOKEN`、`CNB_TOKEN`。
不得输出凭据文件正文、令牌、授权头或预签名上传 URL；不要把令牌直接写进命令行、文档、提交、日志和发布附件。
本页不约定固定凭据文件名或令牌值。确认文件受 `sandbox/` 的忽略规则保护，不能使用 `git add -f`。
令牌权限见 [Gitee 配置](gitee-sync.md) 和 [CNB 配置](cnb-sync.md)。

通用环境变量（以下均非凭据）：

```powershell
$env:RELEASE_TAG = 'v1.0.5-dev1' # 替换为本次 tag
$env:GITHUB_REPOSITORY = 'NeuraXmy/nightreign-overlay-helper'
$env:GH_REPO = $env:GITHUB_REPOSITORY
$env:CNB_REPO = 'NeuraXmy/nightreign-overlay-helper'
$env:PYTHONIOENCODING = 'utf-8'
```

`GITEE_REPO` 优先读取 GitHub 仓库 Actions Variable 的同名配置，并与
[`meta.py`](../../../src/nightreign_overlay/meta.py) 核对；CNB 仓库也应与客户端配置一致。
若配置不存在或不一致，先查明目标仓库，不能静默改用其他仓库。

## 1. 准备提交、版本与说明

1. 检查分支、工作区、远端 main、已有 tag、Release 和正在运行的发布任务。确认没有其他进程发布同一 tag。
2. 更新 `src/nightreign_overlay/__init__.py`。应用版本可写 `1.0.5.dev1`，tag 可写 `v1.0.5-dev1`，
   两者必须经 PEP 440 规范化后相等。预发布状态由应用版本决定，不能仅依据文件名判断。
3. 将用户关心的变化写入 `docs/development/releases/<tag>.md`；需要双语时，先中文、后英文。
   本地 `sandbox/` 中的草稿应整理至该跟踪文件，发布正文使用文件原文。
4. 完成下面的检查后提交源码和说明，保持工作区干净，再创建不可变的 annotated tag。
   不覆盖已存在的远端 tag；所有附件必须对应 tag 的同一个提交。

```powershell
uv sync --locked --python 3.13 --dev --group build
uv run --no-sync python scripts/validate_release_version.py $env:RELEASE_TAG
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
$env:QT_QPA_PLATFORM = 'offscreen'
uv run --no-sync pytest tests -m 'not benchmark' -q --durations=20
uv run --no-sync python scripts/check_runtime_resources.py
dotnet run --project native/NightreignP2PHelper.Tests -c Release
dotnet run --project native/NightreignP2PHelper.RecoveryTests -c Release
git diff --check
```

失败即停止发布并修复；血条检测相关变更还需执行 [完整录像 benchmark](../testing/README.md)。
提交后可用 `git push --atomic origin main <tag>` 同时推送分支和 tag（替换尖括号占位符）。
tag 会触发 Actions；先查看是否已执行，避免与本地发布重复。

## 2. 获取可追溯的两个 ZIP

若同一提交的 CI 产物已通过全部门禁，下载原始程序 ZIP 和源码 ZIP 直接复用，避免重新构建。
若 Actions 在执行前因计费等原因失败，记录失败原因，并在 Windows x64 本地执行与 workflow 相同的门禁和构建。
不要将 Actions 失败本身解释为代码测试失败，也不能跳过门禁。

确认 HEAD 正是 tag 指向的提交，且 `git status --porcelain` 为空，然后运行：

```powershell
$env:CI = '1'
$env:GITHUB_REF_TYPE = 'tag'
$env:GITHUB_REF_NAME = $env:RELEASE_TAG
$env:GITHUB_SHA = git rev-parse HEAD
cmd /c build.bat
# 仅在上一步成功后继续
uv run --no-sync python scripts/prepare_release_licenses.py --check
uv run --no-sync python -m scripts.package_release
```

每一步检查退出码；失败后不继续打包或上传。构建已包括真实后台辅助程序启动检查与原生截图测试程序构建。
`CI=1` 只跳过交互暂停和重复打包，不代替本地回归检查。
`GITHUB_REF_TYPE/NAME` 必须在构建前设置，确保 `SOURCE.md` 指向本次 tag 的源码附件。

将以下两个文件复制或硬链接至全新的 `.tmp/<tag>-assets/` 目录，目录中只能有这两个文件：

- `dist/nightreign-overlay-helper-<tag>-windows-x64.zip`
- `dist/<tag>-sources.zip`

运行 `uv run --no-sync python scripts/validate_release_assets.py .tmp/<tag>-assets <tag>`。
另核对源码清单 `project.commit` 等于 tag 提交、`SOURCE.md` 同版本链接、当前
[`REQUIRED_RUNTIME_FILES`](../../../scripts/package_release.py) 全部存在，并记录两个 ZIP 的大小与 SHA-256。
必须使用本次构建结果，不能拿旧二进制改名配新源码。真实主程序启动、UAC、截图和 Steam 行为的
人工验收范围按 [发布指南](README.md) 记录；自动测试不代表这些实机检查已完成。

## 3. 发布 GitHub

若已有同 tag 的公开 Release，先核对正文、渠道、附件名、大小和 SHA-256；全部一致可直接进入镜像步骤。
不同则停止并查明原因，不自动覆盖公开附件。未完成的 draft 可以校验后续传。

有 `gh` 时使用 `gh release create`，传入 `--verify-tag --title <tag> --notes-file docs/development/releases/<tag>.md`
和两个原始 ZIP 路径。正式版加 `--latest`；开发版加 `--prerelease --latest=false`。
正文必须从文件读取，避免 shell 展开反引号或损坏换行。

没有 `gh` 时可以用进程内 GitHub 凭据调用 REST API，按以下顺序操作：

1. `GET /repos/{repo}/releases/tags/{tag}`；此接口看不到未发布 draft 时，列出 releases 按 tag 查找。
2. 不存在时 `POST /repos/{repo}/releases` 创建 draft，标题为 tag，正文为说明文件原文，
   `target_commitish` 指向 tag 提交，`prerelease` 根据应用版本设置。
3. 向返回的 `upload_url`（去掉模板后缀）逐个上传 ZIP。设置准确的 Content-Length，流式上传，
   日志只记录文件名、进度、HTTP 状态、大小和哈希；不能打印授权头。
4. 对每个附件核对 API 返回的 `size` 和 `digest=sha256:...`。重试时仅跳过名称、大小、哈希均相同的
   draft 附件；同名但内容不同先停止排查。
5. 两个附件均通过后 PATCH Release：`draft=false`；开发版 `prerelease=true, make_latest="false"`，
   正式版 `prerelease=false, make_latest="true"`。
6. 重新 GET 核对 tag、标题、正文、渠道和恰好两个附件。正式版核对 `releases/latest` 指向本次版本；
   开发版核对 Latest 仍为此前正式版。不要上传套有额外目录层的 artifact ZIP。

没有独立说明文件时，自动流程会生成提交说明并追加程序／源码下载提示；手动发布应先准备等价说明文件。

## 4. 同步 Gitee

优先复用 [`sync-gitee.yml`](../../../.github/workflows/sync-gitee.yml) 的手动入口，
指定本次 tag、`diagnostic=false`，并等待成功。Actions 不可用时本地执行同一脚本：

1. 认证读取已公开 GitHub Release，核对 tag、预发布标记及程序附件的大小和 SHA-256。
   下载原程序 ZIP；已有本地文件只有与 GitHub digest 相同才可复用。
2. 在仓库根目录准备 `release/nightreign-overlay-helper-<tag>-windows-x64.zip`。
   `release/` 不是默认忽略目录，不得暂存该目录；可在本地 `.git/info/exclude` 排除它。
3. 确认当前进程已有 `GH_TOKEN`、`GITEE_TOKEN`、`GITHUB_REPOSITORY`、`GITEE_REPO` 和 `RELEASE_TAG`。

```powershell
$env:DIAGNOSTIC_UPLOAD = 'false'
uv run --no-sync python -m scripts.sync_gitee_release
```

脚本调用 `prepare_runtime()` 按最大 50 MiB 切割原始字节，生成 `.001` 等分卷和 `.manifest.json`，
清单最后上传。分卷数量由实际大小决定，不固定为四个。正文必须使用 `mirror_notes()` 的原样输出，
不能手工改写下载说明。tag 指向镜像仓库自身默认分支，不复制上游源码。
同名同大小附件会跳过，不同大小会替换；脚本最终只检查预期附件大小，**不保证清除额外附件或验证远端哈希**。
因此还需对照预期文件列表检查多余附件，并匿名回读所有文件，核对各分卷及清单 SHA-256，
按清单顺序合并后的哈希必须等于 GitHub 原 ZIP。无需分卷时直接核对原 ZIP。

## 5. 同步 CNB

优先复用 [`sync-cnb.yml`](../../../.github/workflows/sync-cnb.yml) 的手动入口。
Actions 不可用时，在本地使用同一触发器；当前进程应已有 `GH_TOKEN`、`CNB_TOKEN`、
`GITHUB_REPOSITORY`、`CNB_REPO` 和 `RELEASE_TAG`：

```powershell
uv run --no-sync python -m scripts.trigger_cnb_sync
```

触发器将当前检出的 `sync_cnb_release.py` 和认证读取的上游元数据传给 CNB `api_trigger`，
使用 Python 3.13 容器；云端自行下载 GitHub ZIP，验证大小和 SHA-256，再上传、确认并回读元数据。
本地只传配置，不向云端发送本地令牌文件或程序大文件。记录构建链接并等待 `success`，
不能只看到“触发成功”就宣布发布完成。等待超时先检查原任务是否仍运行，不并发触发第二次。

脚本支持正式版及开发版，并拒绝 draft、tag 不匹配和未标记为 prerelease 的开发标签。
远端同名附件只有大小及哈希同时相同才跳过。最终核对恰好一个完整程序 ZIP，
`size`、`hash_value` 与 GitHub 一致；标题和正文保持上游原文。预发布不得设为 Latest。

## 6. 完成与重试

- 核对三站版本、标题、正文、预发布标记及上述精确附件集合；Gitee 允许且只允许脚本追加的镜像说明。
- 对正式版使用客户端匿名更新入口验证版本与下载链接；开发版确认不会被
  [`core/updates.py`](../../../src/nightreign_overlay/core/updates.py) 选中。公开网页应能访问附件。
- 镜像失败时保留已经成功的 GitHub Release，修复后只重试失败站点，不重建／重压缩／修改 tag。
  GitHub 公开发布与两个镜像分别记录状态，不因其中一个成功而宣布全部完成。
- 完成后检查 `git status --short`；凭据、日志、构建产物不能进入提交。
  向用户报告三站链接、提交／tag、测试结果和实际未完成的验收项。

[返回发布指南](README.md)
