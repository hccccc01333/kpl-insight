# Series Intelligence Benchmark V1

固定 10 场系列赛，覆盖 BO7/BO5、横扫、让分、单局异常和不同战队；目标是验证**读取、阵营归一化、核心字段和降级处理**，不是给算法刷一个高分。

- 配置：`series_benchmark.json`
- 运行：`python benchmark/run_benchmark.py`
- 依赖：站点的 `assets/schedule_all.js`、`assets/games/index.js`、`assets/games/<league>.json`、`assets/replay/<match>.json`
- 真实数据不随公开仓库分发；请使用自己获准访问的数据，或按相同 schema 提供合成 fixture。

## 当前 Benchmark 覆盖

10 场系列赛，37 局；包含：

- 4:0、4:1、3:0、3:1、2:4、0:1 等比分
- BO7 和 BO5
- 不同战队、不同红蓝方顺序
- 缺少/异常的分钟数据（读取器必须显式降级）

## 判定

每场比较：

- 系列赛队名、比分、BO、局数
- 每局 `battle_id`、局号、双方队名、胜方、时长
- 阵营 ordinal（detail t1=1 / t2=2）
- 能否生成 `schema_version=1.0` 的结构化报告

分钟数据不足或末帧累计回退不会让 benchmark 静默通过为“完整”：报告会带 `data_quality.status=degraded` 和具体原因。

## 不包含

- 关键窗口的人工标注准确率（V1 先把它当候选窗口，不宣称 ground truth）
- 战术因果结论
- 教练意图、选手操作原因
