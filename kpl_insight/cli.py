"""Lazy command dispatch: help works without importing a model or accessing the network."""
import argparse
import runpy
import sys

COMMANDS = {
    "web": ("kpl_insight.web", "启动项目自带前端（默认入口，无需模型）"),
    "demo": ("kpl_insight.demo", "用合成数据离线验证解析、特征和资源事件"),
    "schedule": ("kpl_insight.collection.schedule", "构建官方赛程索引"),
    "backfill": ("kpl_insight.collection.backfill", "按赛程回补终局快照"),
    "leagues": ("kpl_insight.collection.leagues", "归档联赛、系列赛与逐局详情"),
    "dataset": ("kpl_insight.datasets.build", "从赛程和快照生成分析表与训练表"),
    "classify": ("kpl_insight.datasets.quality", "检查快照质量，显式复制 clean/quarantine"),
    "train": ("kpl_insight.models.train", "训练 V12 分阶段模型（需本地数据）"),
    "predict": ("kpl_insight.models.predict", "单局离线重放或联网预测（需模型）"),
    "evaluate": ("kpl_insight.models.evaluate", "在模型记录的测试局上回测"),
    "replay-check": ("kpl_insight.models.replay_check", "对照直播存档与当前模型重放"),
    "monitor": ("kpl_insight.collection.monitor", "按赛程采集并推理（需模型）"),
    "export-live": ("kpl_insight.site.export_live", "导出静态站点的 live.js 与回放分片"),
    "series": ("kpl_insight.analysis.cli", "从本地数据资产生成一场系列赛的证据报告"),
}


def main():
    parser = argparse.ArgumentParser(
        prog="kpl-insight", description="峡谷有数 · KPL Insight（非商业使用）",
        epilog="子命令参数：python -m kpl_insight <command> --help",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", nargs="?", choices=list(COMMANDS),
                        help="\n".join(f"{name}: {description}" for name, (_, description) in COMMANDS.items()))
    argv = sys.argv[1:]
    if not argv:
        from kpl_insight.web import main as web_main
        return web_main()
    if not argv or argv[0] not in COMMANDS:
        parser.parse_args(argv)
        parser.print_help()
        return
    module = COMMANDS[argv[0]][0]
    remaining = argv[1:]
    previous = sys.argv
    try:
        sys.argv = [module, *remaining]
        runpy.run_module(module, run_name="__main__")
    finally:
        sys.argv = previous
