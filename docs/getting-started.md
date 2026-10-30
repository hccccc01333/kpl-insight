# 上手指南

峡谷有数主要供用户自行部署、修改和扩展，做出适合自己的 KPL 数据工具，限非商业使用。可以先在线体验已有功能，再在本地运行并按需修改；无需向原项目提交 PR，也可以独立维护自己的非商业版本。使用、修改和分发须遵守仓库许可，保留适用的许可与署名说明。

## 1. 先在线体验

访问 [在线网站](https://kpldata-site.hccccc01333.workers.dev/)，无需安装或注册。网站主要提供已归档数据、已有历史预测与复盘；也可使用 [GitHub Pages 入口](https://hccccc01333.github.io/KPLdata-site/)。在线浏览不依赖你在本地运行本项目。

## 2. 自己部署：在本机浏览归档数据

前端页面、交互和已归档展示数据已随本项目提供，默认使用这套界面。下载或克隆本项目后，在项目根目录运行：

```bash
python start.py
```

Windows 也可双击根目录的“启动网站.bat”。只需 Python 3.10 或以上，无需安装模型依赖、Node 或另行克隆网站仓库。启动后自动打开 **http://127.0.0.1:8000/**，按 `Ctrl+C` 停止；端口被占用时使用 `python start.py --port 8001`，不自动打开浏览器时加 `--no-browser`。

前端源码及展示数据在 [`kpl_insight/frontend/`](../kpl_insight/frontend/README.md)，可以直接修改 HTML、CSS 和 JavaScript。内置数据是打包时的归档快照；启动网页不等于启动实时采集与预测，部分外部图片和录像仍需联网。

本地页面只提供“一键启动 / 停止”和状态监控。系统自动选择赛事和运行方式：有模型时实时预测，没有模型时仅采集并标注。无需填写 ID、选择模式或输入命令；线上网站不显示此面板。

安装公开版工具后，`python -m kpl_insight` 和 `kpl-insight` 默认打开这套前端。指定参数时运行 `python -m kpl_insight web --port 8001`；`--help` 继续显示所有采集、训练与分析命令。

## 3. 进阶：安装工具与离线演示

使用 Python 3.14，在仓库根目录创建并激活虚拟环境，然后：

```bash
python -m pip install -e .
python -m kpl_insight demo
python -m unittest discover -s tests -v
python tests/check_monitor_rolling.py
```

`demo` 使用合成数据，输出 `output/demo/features.csv`、`snapshots.json` 和 `summary.json`。示例没有训练模型，也没有真实比赛统计。

`python -m kpl_insight <命令> --help` 显示各命令参数。也可以使用安装后的 `kpl-insight` 命令。

## 4. 进阶：采集与整理

```bash
python -m kpl_insight schedule --league-ids 20260004
python -m kpl_insight backfill --missing --limit 5
python -m kpl_insight dataset
python -m kpl_insight classify --dry-run
```

顺序是赛程索引 → 已结束比赛的可用快照 → 分析表与训练表 → 质量检查。`leagues --leagues <ID>` 另行归档联赛与系列赛详情，不会自动把终局数据变成真实分钟序列。

官方接口可能调整、缺字段或返回旧副本；命令成功不代表每场都有完整数据。`backfill` 只会拿到接口当前可返回的状态，历史终局不能替代真实过程。请先指定少量比赛检查结果。

采集接口默认直连。确实需要使用环境代理时设置 `KPL_USE_PROXY=1`。数据与模型输出根目录默认是当前工作目录；可用 `KPL_DATA_ROOT` 指向另一个本地目录。始终在启动 Python 进程前设置环境变量。

## 5. 训练与验证

训练需要 `data/processed/battles.csv`、`players.csv`，以及足够多带胜负标签的真实快照局。`dataset` 会生成前两张表；没有可解析选手信息时不会生成 `players.csv`。首次没有模型时，在比赛期间先采集：

```bash
python -m kpl_insight monitor --league-id 20260004 --collect-only --interval 3
```

此模式不加载模型、不生成胜率，也不触发自动训练。取得足够多真实对局后，再运行 `dataset` 和以下步骤。

`classify` 默认只生成质量清单。首次需要复制合格快照时执行：

```bash
python -m kpl_insight classify --materialize
python -m kpl_insight train
python -m kpl_insight evaluate --gates
```

已有 `clean/` 或 `quarantine/` 数据时，复制命令会拒绝覆盖；自行归档旧目录后再重建。原始快照保留不动。也可通过 `train --from-raw` 绕过分类副本，但这不会自动完成质量筛选。

最低数量检查不代表数据已经足以支持可靠的预测结论。训练会按时间把整局分成训练、校准和测试三段；同一局的快照不能跨段。旧文件名 `v9_official_platform.joblib` 为兼容沿用，实际模型版本查看产物中的 `version`。评估报告应注明模型版本、测试局数与时间范围。

权重在本地生成，本仓库不提供下载的 joblib。只加载自己生成或信任来源的权重，joblib/pickle 不是安全的数据交换格式。

## 6. 单局预测与实时采集

**实时胜率需要本地运行采集与预测程序，不是在线静态网站提供的即开即用云端服务。** 只运行网页 HTTP 服务或 Streamlit 工作台不会替代比赛日监控；本地程序停止后，不再持续产生新预测。公开仓库没有预训练权重，没有模型时先使用第 4 节的 `--collect-only` 积累数据，再训练和验证。运行期间保持终端与网络连接；目标赛事 ID 需按实际比赛调整。

监控结果保存在本地。要让在线静态网站显示新结果，还需导出数据、接入站点并发布；运行监控不会自动推送或部署。

有模型后：

```bash
python -m kpl_insight predict --battle-id YOUR_BATTLE_ID
python -m kpl_insight monitor --league-id 20260004 --interval 3 --no-auto-train
```

`monitor` 需要已有模型；它会采集真实过程快照、记录预测并按赛程切换比赛。首次建库可先用 `backfill` 整理终局，但建立可靠的局内模型仍需要持续取得真实时间序列；不能仅靠几场回补直接训练上线。

## 7. 可选本地工作台

```bash
python -m pip install -e ".[dashboard]"
python -m streamlit run apps/dashboard.py
```

工作台读取本地 `data/analysis/`、`data/processed/` 与 `data/realtime/`。没有数据时相关页面显示为空；线上静态网站的数据不会自动同步到本地。

## 8. 静态站点数据导出

```bash
python -m kpl_insight export-live
```

默认在项目内置的 `kpl_insight/frontend/assets/` 更新 `live.js` 与 `live_hist/`，刷新本地前端即可查看；不推送 Git、不部署。要写入另一份静态站点目录，可在进程启动前设置 `KPL_SITE_DIR`（启动前端时使用相同的目录）。

## 数据口径

`league_id` 表示赛事，`match_id` 表示系列赛，`battle_id` 表示单局。终局详情与真实分钟快照覆盖不同，不能混用样本量。

概率以 `camp1` 为视角；展示前核对阵营与队名映射。`parse_snapshot` 输出 `time_sec` 秒与 `minute` 分钟，训练表的 `game_duration` 使用毫秒。历史直播预测和当前模型重放应分别标识。
