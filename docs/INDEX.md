# 黑夜君临悬浮助手 · 模块知识卡片索引

> 面向 AI 的分层知识库。每张卡片只描述一个层级，便于按任务需要单独加载，不要一次性读取全部。

## 阅读指引

- 先读 [`L0_PROJECT_OVERVIEW.md`](./L0_PROJECT_OVERVIEW.md) 了解目标、范围、目录结构。
- 按任务类型选择对应卡片：
  - 启动/退出/单实例/生命周期 → [`L1_STARTUP.md`](./L1_STARTUP.md)
  - 配置/事件/服务/i18n/前台策略 → [`L2_CORE.md`](./L2_CORE.md)
  - Windows/macOS 平台差异 → [`L3_PLATFORM.md`](./L3_PLATFORM.md)
  - 插件协议/生命周期/依赖解析 → [`L4_PLUGIN_SYSTEM.md`](./L4_PLUGIN_SYSTEM.md)
  - capture/input/hud/region → [`L5_INFRA_PLUGINS.md`](./L5_INFRA_PLUGINS.md)
  - day_timer/rain_timer/art_timer/map_detect/hp_marker/p2p_latency → [`L6_FEATURE_PLUGINS.md`](./L6_FEATURE_PLUGINS.md)
  - 主窗口/页面/悬浮窗/设置卡片 → [`L7_UI.md`](./L7_UI.md)
  - 测试策略与 fixture 约定 → [`L8_TESTING.md`](./L8_TESTING.md)
  - POI CNN 部署、算法切换与验收 → [`POI_CNN.md`](./POI_CNN.md)
  - 多屏截图、DPI 与实机诊断 → [`MULTISCREEN_CAPTURE.md`](./MULTISCREEN_CAPTURE.md)
  - 地图识别样本与回归测试 → [`MAP_DETECT_TESTING.md`](./MAP_DETECT_TESTING.md)
  - 血条识别算法切换、拒识行为与回归测试 → [`HP_DETECTION.md`](./HP_DETECTION.md)
  - 扩大截图区域的血条矩形原型与新视频验证 → [`HP_RECTANGLE_EXPERIMENT.md`](./HP_RECTANGLE_EXPERIMENT.md)
- 修改代码前对照 [`L9_AI_CHECKLIST.md`](./L9_AI_CHECKLIST.md) 核对约束。

## 文档约定

- 文档（包括各目录的 README）只记录对项目使用、维护或复现有普遍价值的信息，避免记录仅与本地开发有关的细节，例如个人环境配置、临时绕过措施和内部工具执行过程。具有普遍性的兼容问题应说明适用条件及通用解决方法。
- 不记录敏感信息，包括真实姓名、个人用户目录及绝对路径、账号、凭据、令牌和私有服务地址。示例优先使用仓库相对路径；必须使用环境相关参数时，使用占位符或环境变量。
- 提交文档前检查正文、命令示例、日志和截图，确认没有泄露本地开发信息或敏感信息。
- 文件路径均相对于仓库根目录 `nightreign-overlay-helper-rewrite/`。
- `→` 表示调用/依赖/数据流向。
- `INVARIANT` 表示不可破坏的约束。
- `PATTERN` 表示推荐的标准做法。

- Debug image storage and retention -> [DEBUG_IMAGES.md](./DEBUG_IMAGES.md)
- 日志与调试图片打包、问题描述及附件导出 → [DIAGNOSTIC_EXPORT.md](./DIAGNOSTIC_EXPORT.md)
