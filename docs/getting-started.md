# 上手指南

## 1. 直接查数据

访问 [静态网站](https://hccccc01333.github.io/KPLdata-site/)。它是单独部署的现有网站，使用静态数据文件，不依赖你本地运行本项目。部分国内网络对 GitHub Pages 的访问仍可能不稳定。

### 本地运行同款静态网站

先安装 Git 和 Python 3。网页源码及已归档的静态数据在独立站点仓库；无需先安装模型工具或训练权重：

```bash
git clone https://github.com/hccccc01333/KPLdata-site.git
cd KPLdata-site
python -m http.server 8000 --bind 127.0.0.1
```

保持该终端运行，在浏览器访问 **http://127.0.0.1:8000/**。关闭服务时按 `Ctrl+C`；若 8000 端口已被占用，将命令中的端口及访问地址一起改为其他可用端口，例如 8001。

通过本地 HTTP 服务打开网页，不要直接双击 HTML：部分数据由页面通过请求加载。数据文件随站点仓库取得，本地页面不会自动同步线上更新；可拉取后续仓库更新，或另行配置下文的数据采集与导出流程。部分头像、图标等外部资源仍可能需要联网，因此这不等于完全离线或保证任何网络环境下可用。

想修改界面，可直接编辑站点仓库的 HTML、CSS 和 JavaScript。仅限本仓库约定的非商业使用范围。喜欢这个项目，也欢迎给 [kpl-insight 主仓库](https://github.com/hccccc01333/kpl-insight) 点 Star，帮助更多同好找到它。

## 2. 安装与离线演示

使用 Python 3.14，在仓库根目录创建并激活虚拟环境，然后：

```bash
python -m pip install -e .
python -m kpl_insight demo
python -m unittest discover -s tests -v
python tests/check_monitor_rolling.py
```

`demo` 使用合成数据，输出 `output/demo/features.csv`、`snapshots.json` 和 `summary.json`。示例没有训练模型，也没有真实比赛统计。

`python -m kpl_insight <命令> --help` 显示各命令参数。也可以使用安装后的 `kpl-insight` 命令。

## 3. 采集与整理

```bash
python -m kpl_insight schedule --league-ids 20260004
python -m kpl_insight backfill --missing --limit 5
python -m kpl_insight dataset
python -m kpl_insight classify --dry-run
```

顺序是赛程索引 → 已结束比赛的可用快照 → 分析表与训练表 → 质量检查。`leagues --leagues <ID>` 另行归档联赛与系列赛详情，不会自动把终局数据变成真实分钟序列。

官方接口可能调整、缺字段或返回旧副本；命令成功不代表每场都有完整数据。`backfill` 只会拿到接口当前可返回的状态，历史终局不能替代真实过程。请先指定少量比赛检查结果。

采集接口默认直连。确实需要使用环境代理时设置 `KPL_USE_PROXY=1`。数据与模型输出根目录默认是当前工作目录；可用 `KPL_DATA_ROOT` 指向另一个本地目录。始终在启动 Python 进程前设置环境变量。

## 4. 训练与验证

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

## 5. 单局预测与实时采集

有模型后：

```bash
python -m kpl_insight predict --battle-id YOUR_BATTLE_ID
python -m kpl_insight monitor --league-id 20260004 --interval 3 --no-auto-train
```

`monitor` 需要已有模型；它会采集真实过程快照、记录预测并按赛程切换比赛。首次建库可先用 `backfill` 整理终局，但建立可靠的局内模型仍需要持续取得真实时间序列；不能仅靠几场回补直接训练上线。

## 6. 可选本地工作台

```bash
python -m pip install -e ".[dashboard]"
python -m streamlit run apps/dashboard.py
```

工作台读取本地 `data/analysis/`、`data/processed/` 与 `data/realtime/`。没有数据时相关页面显示为空；线上静态网站的数据不会自动同步到本地。

## 7. 静态站点数据导出

```bash
python -m kpl_insight export-live
```

默认在 `output/site/assets/` 生成 `live.js` 与 `live_hist/`，不推送 Git、不部署。要写入自己的静态站点源码目录，可在进程启动前设置 `KPL_SITE_DIR`。完整网页源码在独立的 [KPLdata-site 仓库](https://github.com/hccccc01333/KPLdata-site)。

## 数据口径

`league_id` 表示赛事，`match_id` 表示系列赛，`battle_id` 表示单局。终局详情与真实分钟快照覆盖不同，不能混用样本量。

概率以 `camp1` 为视角；展示前核对阵营与队名映射。`parse_snapshot` 输出 `time_sec` 秒与 `minute` 分钟，训练表的 `game_duration` 使用毫秒。历史直播预测和当前模型重放应分别标识。
