# 数据约定

## 三种粒度

- `league_id`：赛事或联赛。
- `match_id`：一次系列赛，例如一个 BO5。
- `battle_id`：系列赛中的一局；不能把局数当作系列赛数。

## 三种覆盖

1. **赛程**包含参赛双方、时间、状态和可能的逐局 ID。
2. **终局详情**包含结束后的局面与选手统计，不表示已经取得完整过程。
3. **真实快照**是在采集时得到的局内状态。只有时间点数量和跨度足够时，才适合过程分析。

合成演示、由终局按比例缩放生成的训练辅助样本与真实采集快照必须区分。不得给历史终局补画“真实分钟曲线”。

## 主要目录

- `data/realtime/schedule_archive.csv`：跨赛事赛程缓存。
- `data/realtime/raw_snapshots/<battle_id>/*.json`：原始接口响应。
- `data/realtime/datasets/`：质量清单与 clean/quarantine 副本。
- `data/analysis/{matches,battles,teams,events}.csv`：面向查询和复盘的表。
- `data/processed/battles.csv`：训练使用的终局表，`game_duration` 为毫秒。
- `data/processed/players.csv`：逐局逐选手表；`position` 为数字分路编码，`position_desc` 为展示文字。
- `data/realtime/predictions/<battle_id>.csv`：历史直播产生的预测存档。
- `output/models/`：本地训练产物，不提交 Git。

官方选手分路编码：`2=中路`、`4=游走`、`5=打野`、`6=对抗路`、`7=发育路`。BP 中的位置编码不同，必须使用对应的解析函数。

`parse_snapshot` 把原始 `game_duration` 转成 `time_sec` 秒和 `minute` 分钟；原始接口常见毫秒时长，字段变化时需先核验单位。

## 概率与复盘

概率以 `camp1` 为视角，不固定等于网站的第一支队伍。必须核对队名与阵营映射。`prob_raw`、`prob_model` 与展示层处理结果应分别记录。

历史直播预测使用当时模型；当前重放使用现在的模型，两者不必相等。解释字段中的输入大小排序是描述性摘要，不是 SHAP 或因果贡献。

数据缺失时保留空值和原因。质量清单、生成时间、样本局数和模型版本应与报告一起保存。
