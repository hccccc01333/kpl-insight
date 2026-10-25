"""
构建 KPL 跨赛季赛程索引

Notebook 发现：
`https://prod.comp.smoba.qq.com/leaguesite/matches/open?league_id=...`
可以通过 league_id 拉取对应赛事赛程；赛程行包含 match_id、start_time、
双方队伍和 match_battle_video_list（可解析出 battle_id 列表）。

运行：
    python -m kpl_insight.collection.schedule --from-local
    python -m kpl_insight.collection.schedule --start-year 2018 --end-year 2026
    python -m kpl_insight.collection.schedule --date 2026-05-23
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import pandas as pd

from kpl_insight.core import PROJECT_ROOT, SCHEDULE_ARCHIVE_PATH, ScheduleCenter, normalize_schedule_archive_frame


def build_from_local() -> pd.DataFrame:
    src = PROJECT_ROOT / "data" / "processed" / "schedule.csv"
    if not src.exists():
        raise FileNotFoundError(f"not found: {src}")
    df = pd.read_csv(src, dtype={"league_id": str, "match_id": str}).fillna("")
    archive = normalize_schedule_archive_frame(df)
    SCHEDULE_ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    archive.to_csv(SCHEDULE_ARCHIVE_PATH, index=False, encoding="utf-8-sig")
    return archive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-local", action="store_true", help="从 data/processed/schedule.csv 构建缓存")
    parser.add_argument("--start-year", type=int, default=2018)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--event-start", type=int, default=1)
    parser.add_argument("--event-end", type=int, default=12)
    parser.add_argument("--league-ids", nargs="*", default=None, help="显式指定 league_id 列表")
    parser.add_argument("--date", default=None, help="构建后按 YYYY-MM-DD 查询当天赛程")
    parser.add_argument("--team", default=None, help="按战队关键字筛选")
    args = parser.parse_args()

    center = ScheduleCenter()
    if args.from_local:
        archive = build_from_local()
    else:
        league_ids = args.league_ids if args.league_ids else None
        archive = center.build_schedule_archive(
            league_ids=league_ids,
            start_year=args.start_year,
            end_year=args.end_year,
            event_codes=range(args.event_start, args.event_end + 1),
        )

    print(f"archive rows: {len(archive)}")
    print(f"saved: {SCHEDULE_ARCHIVE_PATH}")

    if args.date or args.team:
        result = center.query_schedule_archive(date=args.date, team_keyword=args.team)
        cols = ["date", "start_time", "league_id", "match_id", "team1", "team2", "stage", "battle_count", "battle_ids"]
        print(result[cols].to_string(index=False) if not result.empty else "no matches")


if __name__ == "__main__":
    main()
