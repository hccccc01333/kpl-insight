# Series Intelligence V1 · 系列赛证据报告

这是 `kpl-insight` 0.2.0 的核心模块：输入一场已结束的 BO3/BO5/BO7，输出可追溯的结构化报告，并让 CLI 与网站读取同一份 JSON。

## 快速运行

```bash
# 在核心仓库根目录
python -m kpl_insight.cli \
  --match-id 2026102201 \
  --site-dir ../kpl-data-center-site \
  --out reports/series_analysis/2026102201.json \
  --md reports/series_analysis/2026102201.md
```

安装后也可以直接调用：

```bash
pip install -e .
analyze-series --match-id 2026102201 \
  --site-dir ../kpl-data-center-site \
  --out reports/series_analysis/2026102201.json
```

## 输入数据

V1 复用公开站点的生成资产，避免另造一套口径：

```text
<site-dir>/
  assets/schedule_all.js          # 大场结果、比分、BO、战队
  assets/games/index.js           # match -> battle 索引
  assets/games/<leagueId>.json    # 逐局详情：比分、BP、选手、经济
  assets/replay/<matchId>.json    # 分钟帧与事件（可选）
```

外部用户可以使用自己的同 schema 数据；没有分钟帧时报告仍可生成，但会明确降级，不会补造。

## 输出

`report.json` 固定结构：

- `series`：官方比分、BO、队名、日期
- `headline`：一句话结论
- `data_quality`：帧/BP 覆盖、警告、隔离记录
- `games[]`：每局阵营、胜方、5/8/10 分钟检查点、候选窗口、覆盖度
- `series_comparison`：早期领先、翻回、时长、资源累计、阵营顺序
- `conclusion`：`facts` / `inferences` / `hypotheses` 三层
- `limits`：口径限制

`report.md` 是人类阅读版；网站 `match.html` 读取同一份 JSON，不在前端重算。

## 数据质量规则

- 大场比分必须等于逐局胜方汇总；不一致直接报错。
- 阵营按**队名**归一化，不按 `camp1/team1` 的顺序；G1/G4 与 G2/G3 换边时仍能正确统计。
- 击杀、推塔、资源累计计数只能单调不减；发现回退时隔离该帧及之后帧，记录具体分钟和字段，不使用异常帧。
- 缺失 BP/帧/选手只做显式降级，不默认填 0。

## Benchmark

```bash
python benchmark/run_benchmark.py
```

固定 10 场、37 局，验证读取和核心字段；详见 `benchmark/README.md`。

## 案例

`reports/series_analysis/2026102201.json` / `.md`  
2026-10-22 杭州LGD.NBW 4:0 南通Hero久竞：首轮报告发现四局末段累计计数异常；修复 replay 构建器（跳过 status=2 终局摘要帧）后，正式报告状态为 `ok`。

## 限制

- 候选窗口不是因果结论；没有直播胜率时只看金差代理。
- 没有教练语音、训练赛、伤停、版本 patch 字段，不能判断指挥责任或战术意图。
- 公开仓库不重新分发第三方赛事原始数据。
