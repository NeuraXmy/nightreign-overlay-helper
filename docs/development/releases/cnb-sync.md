# CNB 更新源与云原生同步

CNB 镜像地址为 <https://cnb.cool/NeuraXmy/nightreign-overlay-helper>。GitHub 继续测试、构建 Windows 程序并发布 Release；CNB 云原生构建拉取同一个程序 ZIP，验证 GitHub 提供的文件大小和 SHA-256，再上传至 CNB Release。Linux 构建容器只负责同步，不重新打包 Windows 程序。CNB 直接保存完整 ZIP，无需 Gitee 的分卷方案；程序源码继续从 GitHub 同版本 Release 获取。

## 配置和自动触发

1. CNB 创建公开仓库，默认分支为 `main`，至少包含一个初始提交。镜像仓库可只维护说明和同步配置，不必镜像项目全部源码。
2. GitHub Actions Secret `CNB_TOKEN` 保存 CNB 访问令牌，需要 `repo-release:rw`、`repo-code:r`、`repo-cnb-trigger:rw`；查看历史使用 `repo-cnb-history:r`。访问令牌只用于服务端触发和管理，不写入客户端。构建中的发布由 CNB 自动注入的 `CNB_TOKEN` 完成。
3. [`release-windows.yml`](../../../.github/workflows/release-windows.yml) 正式版 GitHub Release 发布成功后调用 [`sync-cnb.yml`](../../../.github/workflows/sync-cnb.yml)，与 Gitee 同步任务独立。预发布版本不触发此镜像。
4. [`trigger_cnb_sync.py`](../../../scripts/trigger_cnb_sync.py) 获取 GitHub Release 元数据，将当前检出的同步脚本作为 `config` 传给 CNB 的 `api_trigger` 构建。GitHub 仅传输配置和元数据，不上传程序大文件。任务等待 CNB 结束，失败会令 GitHub 同步任务失败并给出 CNB 构建链接。
5. CNB 使用 Python 3.13 容器运行 [`sync_cnb_release.py`](../../../scripts/sync_cnb_release.py)。从 GitHub 下载程序包后，先验证大小和 SHA-256，再创建／更新 Release，获取预签名地址、上传并确认附件，最后重新读取元数据验证大小和哈希。相同附件已完整发布时跳过上传。下载／上传记录耗时、HTTP 状态、字节数和平均速度，不输出令牌和签名 URL。

若 GitHub 已发布但 CNB 同步失败，在 **Actions → Sync Release through CNB Cloud Build → Run workflow** 输入原正式版 tag 重试，无需重建。同步整体等待 20 分钟，单次文件传输最多 15 分钟。等待超时后先检查 CNB 构建是否仍在运行，避免并发重复发布。

CNB 仓库也保留 [`mirror.cnb.yml`](../../../scripts/cnb/mirror.cnb.yml) 的最小配置示例。直接在 CNB 手动运行它时，需提供 `RELEASE_TAG`；推荐使用 GitHub 触发入口，它会附带经过 GitHub 身份验证获取的元数据，避免 CNB 匿名请求 GitHub API 的频率限制。

## 客户端匿名检查

GitHub、Gitee、CNB 同时在后台检查，共享 10 秒期限，采用成功来源中的最高正式版本。同版本按 GitHub、Gitee、CNB 顺序优先；CNB 出现更高版本时选择 CNB。下载、速度显示、取消和“跳过该版本”沿用现有机制。

CNB 公开 Release API 当前要求登录，客户端因此读取公开 Release 页面中 `__NEXT_DATA__` 的结构化版本和附件数据，不携带令牌。解析字段异常会记录来源检查失败，并保留其他来源检查结果。公开页面只提供近期版本时，日志界面显示历史不完整提示，并给出三个站点入口。CNB 页面结构变化可能需要更新解析逻辑。附件只接受同仓库、对应 tag 和预期 Windows ZIP 文件名的公开下载路径。

## 验证记录（2026-10-22）

- CNB 云原生构建从 GitHub 下载 `v1.0.2` 程序包（202,404,389 字节）用时 31.2 秒，平均约 6.48 MB/s；内部上传用时 3.6 秒，平均约 56.1 MB/s；远端附件 SHA-256 校验通过。这是单次实测，不保证后续网络速度。
- CNB 假 `v1.0.3` 用于版本选择与下载验证，正文明确标注为测试。附件仅为包含 `TEST-ONLY.txt` 的 192 字节 ZIP，不是可运行程序，不应安装。完成测试后应删除该 Release；在它存在期间，新客户端会按正常版本规则发现它。
- 本地实际匿名检查选中 CNB `v1.0.3` 并下载测试 ZIP，大小和 SHA-256 与上传文件一致。

[返回发布指南](README.md)
