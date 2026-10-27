# 结构与数据流

这个仓库承载数据采集、处理和模型工具；线上静态网站由独立仓库部署。两者通过生成的数据文件连接。

```text
官方公开接口
  ├─ collection.schedule  → data/realtime/schedule_archive.csv
  ├─ collection.backfill  → 可回补的终局快照
  ├─ collection.monitor   → 比赛期间真实快照 + frames + predictions
  └─ collection.leagues   → data/history/ 联赛与系列赛归档

赛程索引 + raw_snapshots
  → datasets.build        → data/analysis/ + data/processed/
  → datasets.quality      → 质量清单 + 可选 clean/quarantine 副本

处理后的表 + 合格真实快照
  → models.train          → output/models/ + train_status.json
  → models.predict        → 单局重放或一次性联网推理
  → models.evaluate       → 模型记录的测试局指标
  → models.replay_check   → 历史直播存档与当前重放差异

本地表 / 快照 / 预测
  ├─ apps/dashboard.py    → 本地 Streamlit 工作台
  └─ site.export_live     → output/site/assets/ → 自行接入静态站点
```

`core.py` 集中快照解析、特征构造、推理、事件和复盘算法；各入口复用这些函数，避免训练、直播与重放各维护一套特征。当前共享模块仍较大，后续拆分应保持契约与测试稳定。

`models/display.py` 负责概率区间、低置信提示、先验混合与平滑。它是展示层；展示值不应冒充原始模型输出。加载可选校准表时检查模型指纹。

`KPL_DATA_ROOT` 控制运行数据根目录，默认当前工作目录；打包的术语知识资源位于 `kpl_insight/resources/`，不依赖用户的本地文档目录。

公开目录不包含开发者个人路径、自动推送脚本、部署凭据、权重、原始媒体和研究过程文件。
