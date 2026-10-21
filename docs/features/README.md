# 功能文档

本目录说明当前功能的输入、配置、实现入口和运行边界。用户操作细节以应用内各功能的“教程”选项卡为准；教程源码位于 `src/nightreign_overlay/plugins/<id>/tutorial/`。

| 主题 | 内容 |
| --- | --- |
| [基础能力](infrastructure.md) | 截图、热键、共享 HUD、区域标定与音频服务 |
| [自动识别区域](automatic-regions.md) | 16:9 游戏客户区适配、逐区域手动优先与快捷键兼容 |
| [计时功能](timers.md) | 缩圈、雨中冒险、绝招计时及音频播报 |
| [地图信息](map/README.md) | 识别状态机、候选、手动筛选、快捷键与地图数据 |
| [地图 POI CNN](map/poi-cnn.md) | 生产推理、类别约束、模型与验收入口 |
| [血量阈值标记](hp/README.md) | 标定、检测范围、参考线和拒识行为 |
| [血条材质与端点检测](hp/material-detection.md) | 模型特征、分割、连续确认与训练边界 |
| [联机状态](p2p.md) | Steam／ETW 辅助程序、组件路径与 macOS 模拟 |
| [队友时长、主页与赛后点赞](steam-social.md) | 免密钥时长、名字跳转、独立点赞页、限时窗口与七天防重复 |

涉及功能启停或跨插件通信时，同时阅读[插件系统](../architecture/plugin-system.md)。固定样本评估与优化过程见[实验记录](../development/experiments/README.md)，不作为通用使用说明。

[返回文档总索引](../INDEX.md)
