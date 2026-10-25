# -*- coding: utf-8 -*-
"""analyze-series CLI · 可复现的 KPL 系列赛证据报告。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from kpl_insight.analysis import analyze_series, load_series, render_markdown
from kpl_insight.analysis.loaders import DEFAULT_SITE_DIR


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="analyze-series",
                                description="从公开站点数据生成一场系列赛的结构化证据报告")
    p.add_argument("--match-id", required=True, help="官方 match_id，例如 2026102201")
    p.add_argument("--site-dir", default=str(DEFAULT_SITE_DIR),
                   help="站点资产目录（含 assets/schedule_all.js 等）")
    p.add_argument("--out", default=None, help="report.json 输出路径")
    p.add_argument("--md", default=None, help="report.md 输出路径")
    p.add_argument("--quiet", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    series = load_series(args.match_id, args.site_dir)
    report = analyze_series(series)

    out = Path(args.out) if args.out else Path("reports") / "series_analysis" / f"{args.match_id}.json"
    md = Path(args.md) if args.md else out.with_suffix(".md")
    out.parent.mkdir(parents=True, exist_ok=True)
    md.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md.write_text(render_markdown(report), encoding="utf-8")

    if not args.quiet:
        s = report["series"]
        print(f"{s['team1']} {s['score1']}:{s['score2']} {s['team2']} · "
              f"{len(report['games'])} 局 · 数据状态 {report['data_quality']['status']}")
        print(report["headline"])
        print(f"JSON -> {out}")
        print(f"MD   -> {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
