# Gitee Release 镜像配置

Gitee 仓库面向国内下载与更新检查，只维护 Release、更新日志和附件，不推送 GitHub 源码或提交历史。Gitee 仅上传程序，不上传对应源码 ZIP；GitHub Release 继续保留程序和源码附件，镜像正文提供同版本源码的直达链接。

## 首次配置

1. 在 Gitee 创建**公开仓库**，默认地址为 `NeuraXmy/nightreign-overlay-helper`。创建时勾选初始化 README，确保存在默认分支和至少一个提交。Gitee 的 Release 必须绑定 tag；同步脚本基于 Gitee 自身默认分支的初始提交创建 tag，不同步 GitHub 源码。不要使用依赖访问者登录的私有仓库。
2. 在 Gitee 的个人设置中创建私人令牌，授权访问该仓库和管理 Release／上传附件所需的 `projects` 权限。令牌拥有者必须具有仓库发布权限。检查 Gitee 账户、单附件大小和仓库配额是否能容纳实际程序分卷。
3. 在 GitHub 仓库 **Settings → Secrets and variables → Actions → Secrets** 添加 `GITEE_TOKEN`。令牌只由发布任务读取，不能提交进仓库或写入应用配置。
4. 在同一页面的 **Variables** 添加 `GITEE_REPO`，值为 `NeuraXmy/nightreign-overlay-helper`（不要包含域名或协议）。该值用于 Actions 同步。
5. 应用内更新检查地址在 [`meta.py`](../../../src/nightreign_overlay/meta.py) 的 `GITEE_REPO` 常量中；如实际使用其他仓库，修改此常量后再构建，并使其与 Actions 变量一致。客户端仅匿名访问公开 API，不包含令牌。
6. 工作流进入默认分支后，在 **Actions → Sync Release to Gitee → Run workflow** 输入 `v1.0.1`，将已有正式版补齐到镜像。对其他历史正式版逐个执行，确保应用内从 v1.0.1 起的日志齐全。

## 自动发布和补同步

推送版本 tag 后，`Release Windows ZIP` 完成验证、构建和 GitHub Release 发布，再调用 [`Sync Release to Gitee`](../../../.github/workflows/sync-gitee.yml)。同步读取已发布的 GitHub Release 标题、正文、预发布状态，只下载并核对程序 ZIP。程序不超过 50 MiB 时直接上传；超过时按原始字节拆成最多 50 MiB 的 `.zip.001`、`.zip.002` 等分卷，生成 `.zip.manifest.json`（完整文件名、总大小、完整 ZIP 及各分卷 SHA-256），再上传并核对附件大小。清单最后上传，避免客户端提前下载不完整的分卷集合。

GitHub 发布成功但镜像失败时，GitHub Release 保留可用，Actions 会明确显示镜像任务失败。配置好凭据、权限或配额后，手动运行同步 workflow，填写原 tag 即可重试，无需重建程序。相同名称和大小的附件跳过；同名而大小不符的附件会被替换。手动修改 GitHub Release 正文后，也通过此入口重新同步。

同步不会复制 GitHub tag 对应的源码提交到 Gitee。因此 Gitee 自动生成的“源码”归档只是镜像仓库初始内容，**实际对应源码应从 GitHub 同版本 Release 下载 `<tag>-sources.zip` 附件**。应用的下载按钮支持完整程序 ZIP，以及清单和分卷，不会下载源码。

## 上传日志与网络诊断

每个附件上传时记录名称、大小和超时，每 15 秒输出已发送比例、数据量、平均速度和当前速度。结束时记录 curl 退出码、HTTP 状态、远端 IP、DNS／TCP／TLS／开始传输／首次响应及总耗时、发送字节数与平均上传速度。日志使用 UTC 时间，不输出令牌、请求表单或服务端正文。正常同步保留单附件 30 分钟超时。

上传停滞时，在 **Actions → Sync Release to Gitee → Run workflow** 填写已有 GitHub tag，勾选 `diagnostic`。诊断仍从 GitHub Runner 实际上传同一程序分卷，但目标是独立的 `<tag>-uploadcheck-<run-id>` 临时预发布页，不会跳过已有正式附件或替换正式版。诊断的单附件超时为 300 秒；无论成功还是失败，工作流的清理步骤都会删除临时 Release 及其附件（镜像仓库生成的 tag 保留）。若任务被强制终止导致清理未执行，可按日志中的临时 tag 手动删除对应 Release。

判断方法：连接／TLS 耗时高表示建立连接慢；连接迅速但已发送字节持续不增长，表示上传链路或服务端接收停滞；发送达到 100% 后迟迟没有最终响应，表示请求体已发送、仍在等待服务端处理。HTTP 403／429 与持续低速是不同的问题；HTTP `000` 表示未收到最终 HTTP 状态，需结合 curl 退出码和发送字节判断。诊断不会自动改变分卷大小、网络协议或增加重试，以免干扰首次观测。

手动运行时可通过 `runner` 选择 `ubuntu-latest`、`ubuntu-24.04-arm`、`windows-2022` 或 `macos-15`，配合 `diagnostic` 比较 GitHub 官方托管环境的上传速度。工作流记录系统、架构和 curl 版本；各次运行使用独立临时 Release。正常自动同步默认使用 `windows-2022`；单附件超时为 30 分钟，整个任务超时为 120 分钟。50 MiB 按本次 Windows 实测约 45 KiB/s 估算需约 19 分钟，完整程序仍需约 73 分钟；后续速度会随网络变化。GitHub 官方说明 Windows／Ubuntu 托管在 Azure，macOS 使用独立的 macOS 云；选择系统不等于选择地区，也不保证某个标签的网络速度始终更快。

## 手动下载分卷

下载同版本全部 `.zip.001`、`.zip.002` 等分卷至同一目录，不要直接解压单个分卷。在 Windows 命令提示符 **cmd** 中运行（将版本替换为实际 tag）：

```bat
copy /b "nightreign-overlay-helper-v1.0.1-windows-x64.zip.???" "nightreign-overlay-helper-v1.0.1-windows-x64.zip"
certutil -hashfile "nightreign-overlay-helper-v1.0.1-windows-x64.zip" SHA256
```

将结果与 `.manifest.json` 的顶层 `sha256` 比较，一致后完整解压。分卷只是将原 ZIP 按字节切开，合并后与 GitHub 原始 ZIP 完全一致；不是需要密码或特定压缩软件的压缩分卷。

## 客户端行为与验证

关于页面位于“项目”和“致谢”之间的“检查更新”组提供更新日志、立即检查和自动检查开关（默认开启）。每次启动仅后台检查一次，无更新或联网失败时静默；手动检查显示成功或失败结果。开关修改在下一次启动生效。

两个站点同时请求，共享 10 秒等待上限。比较两个源获取到的最新正式版本，采用版本较新的源；版本相同时优先 GitHub。只有一个源成功时采用该源。日志按版本降序展示 v1.0.1 起的正式版，排除草稿和预发布，不混入旧版历史。日志联网加载，支持 Release 列表分页。GitHub API 返回 403／429 时，在同一个 10 秒期限内回退公开 Release Atom 订阅源；订阅源仅包含近期版本，日志窗口会明确提示并提供完整历史入口。两站均不可用时，手动检查显示各站点的错误，日志也记录具体原因。

发现新版本后弹出版本和 Markdown 更新日志。下载按钮在后台将检查来源站点的 Windows ZIP 保存至用户选择的位置；Gitee 返回分卷时，客户端按清单顺序下载、边下载边合并，核对各分卷及完整 ZIP 的 SHA-256，最终只保存一个完整 ZIP，不需要用户手动合并。任何分卷缺失、网络中断或校验失败都会清理临时文件并保留已有目标文件。完成后打开所在目录；失败时可使用窗口内两个站点的链接自行下载。下载连接／读操作的超时为 10 秒，大文件下载本身允许超过 10 秒。退出应用不等待后台网络请求。

更新时完整解压新版本，退出旧程序后删除旧程序文件夹；设置保存在用户数据目录，继续保留。使用自定义 `--data-dir` 的用户应继续沿用原路径，避免将设置目录与旧程序一起删除。

发布前实际检查：两个站点匿名 API 均能读取正式版与附件；仅一个站点可达时可以检查；附件能在国内外网络下载；Windows 打包程序能展示日志和保存 ZIP。本地离线测试覆盖版本筛选、双站回退、检查期限和下载失败清理，不能代替 Gitee 账号权限和 Windows 实际联网验收。

[返回发布指南](README.md)
