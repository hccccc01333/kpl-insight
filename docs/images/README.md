# README 视觉素材

`hero.svg` 与 `hero-mobile.svg` 是本项目的品牌封面，源文件可直接编辑。

以下界面截图于 2026-10-25 从已部署的 [GitHub Pages 静态网站](https://hccccc01333.github.io/KPLdata-site/) 获取，未经内容修改：

- `overview.jpg`、`overview-mobile.jpg`：网站首页。
- `schedule-current.jpg`：`schedule.html`，赛程查询。
- `player-current.jpg`：`player.html?id=一诺`，选手数据。
- `heroes-current.jpg`：`heroes.html`，英雄数据。
- `replay-current.jpg`：`match.html?id=2026062603&g=3&m=13`，有真实快照的历史复盘。

截图是界面展示，数据和页面会随站点更新。

## 2026-10-27 本地版本截图

以下截图来自实际运行的本地静态站点，使用 Edge 无头浏览器，以减少动态效果的设置加载真实页面。未替换页面数据、未绘制模拟界面；部分页面通过正常选择英雄、展开时间轴或滚动到对应模块后截图。

这些截图可能先于线上发布，不表示所有内容已部署。截图中的数字是当时页面与筛选范围的结果，不替代 README 中单独注明日期的数据覆盖快照。

- `replay-20261027.jpg`：`match.html?id=2026062603&g=3&m=13`，展开后的复盘时间轴、经济与资源面板。
- `simulator-20261027.jpg`：`simulator.html`，赛前大场与比分模拟。
- `sandbox-20261027.jpg`：`sandbox.html`，胜率地图、模型判断与相似历史状态。
- `hero-performance-20261027.jpg`：`hero-performance.html?player=一诺`，选择英雄后的指标参照与比赛证据。
- `bp-studio-20261027.jpg`：`bp-studio.html?id=2026102201&g=1`，最终阵容视图。
- `team-bp-20261027.jpg`：`team-bp.html`，英雄使用、偏好与五种竞争状态。
- `coach-20261027.jpg`：`coach.html`，任期、来源与 BP 指纹。
- `series-20261027.jpg`：`series.html`，首局与系列赛结果研究。
- `compare-20261027.jpg`：`compare-player.html`，选手雷达和指标对比。
- `series-report-20261027.jpg`：`match.html?id=2026102201`，系列赛证据报告。
- `team-20261027.jpg`：`team.html?id=成都AG超玩会`，战队档案。
- `mobile-20261027.jpg`：`index.html`，430 × 932 手机视口下的首页。

桌面截图视口为 1440 × 1050，JPEG 格式。页面截图中的队标、人物及英雄图片等素材仍属于相应权利人，不因存放在代码仓库中而重新授权。
# 项目沿革与技术示意图

以下 SVG 为本项目编写的可编辑矢量图，不是运行界面截图：

- `project-journey.svg`：2024–2026 项目阶段；展示早期探索、模型工程与产品功能的发展阶段。
- `architecture-overview.svg`：系统全景与模块分工。
- `collection-flow.svg`：比赛日采集、异常重试、原始归档与预测。
- `model-pipeline.svg`：整局按时间划分的训练、校准与独立评估。
- `series-evidence-flow.svg`：系列赛检查、统一报告与各展示端。
- `site-publishing-flow.svg`：本地数据生产、静态构建、发布与浏览访问。

图中描述模块职责与数据流，不代表所有步骤均已配置为自动执行。SVG 不依赖外部图片、脚本或在线字体。

# 交互 GIF

`timeline-demo.gif`、`hero-demo.gif`、`bp-demo.gif`、`simulator-demo.gif` 于 2026-10-27 从本地站点正常操作采样录制，分别展示时间轴、英雄切换、逐手 BP 和模拟条件调整。未替换页面数据或绘制模拟界面。

演示为无声、抽帧加速 GIF，不是原速完整录像，也不代表当前线上已经部署同一版本。桌面视口为 1280 × 900，输出宽度 960，约每秒 6 帧，循环播放。文件只含页面画面，不含音轨、账户信息或浏览器个人界面。

项目时间线展示早期数据探索、模型工程与网站分析工具的演进。
