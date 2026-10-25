"""
KPL 历史数据回补爬虫

从 schedule_archive.csv 读取历史 match/battle 列表，批量拉取 battle/open 数据，
保存到 data/realtime/raw_snapshots/{battle_id}/backfill_*.json。

运行：
    python -m kpl_insight.collection.backfill --dry-run
    python -m kpl_insight.collection.backfill --date 2026-05-23
    python -m kpl_insight.collection.backfill --team AG --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from kpl_insight.core import RAW_DIR, REALTIME_DIR, ScheduleCenter, fetch_freshest_battle


BACKFILL_STATUS_FILE = REALTIME_DIR / "backfill_status.json"


def write_status(payload: dict):
    BACKFILL_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **payload}
    BACKFILL_STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_battle(battle_id: str, payload: dict):
    out_dir = RAW_DIR / battle_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def collect_targets(center: ScheduleCenter, date: str | None, team: str | None, limit: int | None):
    archive = center.query_schedule_archive(date=date, team_keyword=team)
    targets = []
    for _, row in archive.iterrows():
        for battle_id in str(row.get("battle_ids", "")).split("|"):
            if battle_id:
                targets.append(
                    {
                        "league_id": row.get("league_id", ""),
                        "match_id": row.get("match_id", ""),
                        "battle_id": battle_id,
                        "date": row.get("date", ""),
                        "team1": row.get("team1", ""),
                        "team2": row.get("team2", ""),
                    }
                )
    dedup = []
    seen = set()
    for item in targets:
        if item["battle_id"] in seen:
            continue
        seen.add(item["battle_id"])
        dedup.append(item)
    return dedup[:limit] if limit else dedup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="按日期回补 YYYY-MM-DD")
    parser.add_argument("--team", default=None, help="按战队关键字回补")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--missing", action="store_true", help="只回补本地没有快照文件的对局")
    parser.add_argument("--jobs", type=int, default=1, help="并发拉取数（默认 1；建议 ≤6）")
    parser.add_argument("--retries", type=int, default=1, help="单场拉取失败后的重试次数（默认 1）")
    parser.add_argument("--retry-backoff", type=float, default=3.0, help="重试退避基数（秒）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.4)
    args = parser.parse_args()

    center = ScheduleCenter()
    targets = collect_targets(center, args.date, args.team, args.limit)
    if args.missing:
        before = len(targets)
        targets = [
            t for t in targets
            if not (RAW_DIR / t["battle_id"]).exists()
            or not any((RAW_DIR / t["battle_id"]).glob("*.json"))
        ]
        print(f"--missing: {before} -> {len(targets)} 个缺快照对局")
    write_status({"state": "planning", "target_count": len(targets), "dry_run": args.dry_run})
    print(f"targets: {len(targets)}")
    if args.dry_run:
        for item in targets[:30]:
            print(f"{item['date']} {item['match_id']} {item['battle_id']} {item['team1']} vs {item['team2']}")
        write_status({"state": "dry_run_done", "target_count": len(targets)})
        return

    ok = 0
    failed = 0
    total = len(targets)

    def _fetch(battle_id: str):
        for attempt in range(max(1, int(args.retries) + 1)):
            raw = fetch_freshest_battle(battle_id, n_probes=2, gap_sec=0.3)
            if raw is not None:
                return raw
            if attempt < int(args.retries):
                time.sleep(float(args.retry_backoff) * (attempt + 1))
        return None

    def handle(i: int, item: dict, raw: dict | None) -> None:
        nonlocal ok, failed
        battle_id = item["battle_id"]
        if raw:
            path = save_battle(battle_id, raw)
            ok += 1
            print(f"[{i}/{total}] OK {battle_id} -> {path.name}", flush=True)
        else:
            failed += 1
            print(f"[{i}/{total}] FAIL {battle_id}", flush=True)
        write_status(
            {
                "state": "running",
                "target_count": total,
                "processed": i,
                "success": ok,
                "failed": failed,
                "current_battle_id": battle_id,
            }
        )

    jobs = max(1, int(args.jobs))
    if jobs == 1:
        for i, item in enumerate(targets, 1):
            handle(i, item, _fetch(item["battle_id"]))
            time.sleep(args.sleep)
    else:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(_fetch, t["battle_id"]): t for t in targets}
            for i, fut in enumerate(as_completed(futures), 1):
                item = futures[fut]
                try:
                    raw = fut.result()
                except Exception as e:
                    print(f"[{i}/{total}] ERROR {item['battle_id']}: {type(e).__name__}", flush=True)
                    raw = None
                handle(i, item, raw)

    write_status({"state": "done", "target_count": total, "success": ok, "failed": failed})


if __name__ == "__main__":
    main()
