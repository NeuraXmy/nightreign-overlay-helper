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
  - 地图识别样本与回归测试 → [`MAP_DETECT_TESTING.md`](./MAP_DETECT_TESTING.md)
- 修改代码前对照 [`L9_AI_CHECKLIST.md`](./L9_AI_CHECKLIST.md) 核对约束。

## 文档约定

- 文件路径均相对于仓库根目录 `nightreign-overlay-helper-rewrite/`。
- `→` 表示调用/依赖/数据流向。
- `INVARIANT` 表示不可破坏的约束。
- `PATTERN` 表示推荐的标准做法。
