# -*- coding: utf-8 -*-
"""KPL 全历史回补：2019–2026 全部联赛的赛程 / 逐局 / BP / 选手 / 视频。

数据源：腾讯 KPL 官方公开接口（直连，独立于仓库既有快照）。
输出（原始 JSON 原样落盘，断点续传，重复运行自动跳过已完成）：

  data/history/leagues.json                         联赛总表
  data/history/<league_id>/schedule.json            该联赛赛程（官方原始数组）
  data/history/<league_id>/matches/<match_id>.json  该大场全部逐局详情

用法：
  python backfill_league_history.py --leagues 20250001 20250002
  python backfill_league_history.py --all --jobs 8
  python backfill_league_history.py --all --jobs 8 --summary
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kpl_insight.core import (  # noqa: E402
    PROJECT_ROOT,
    api_get,
    BASE_URL_BATTLE,
    BASE_URL_LEAGUE,
    BASE_URL_LEAGUES,
    BASE_URL_MATCH,
)

HIST = PROJECT_ROOT / "data" / "history"

_lock = threading.Lock()
_stats = {"matches_new": 0, "matches_skip": 0, "battles_new": 0, "requests": 0, "errors": 0}


def jdump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def jdump_if_changed(path: Path, obj) -> bool:
    """内容未变不落盘：schedule.json 会被站点监视器当输入，每 90 秒无脑重写会触发构建风暴。"""
    body = json.dumps(obj, ensure_ascii=False)
    try:
        if path.read_text(encoding="utf-8") == body:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)
    return True


def jload(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def api(url, params, timeout=15, retries=3):
    for i in range(retries):
        with _lock:
            _stats["requests"] += 1
        d = api_get(url, params, timeout=timeout)
        if d and (d.get("results") is not None or d.get("data") is not None):
            return d
        time.sleep(0.6 * (i + 1))
    with _lock:
        _stats["errors"] += 1
    return None


def get_leagues() -> list[dict]:
    path = HIST / "leagues.json"
    cached = jload(path)
    if cached:
        return cached
    d = api(BASE_URL_LEAGUES, None)
    res = (d or {}).get("results") or []
    leagues = [
        {
            "league_id": str(l["league_id"]),
            "league_name": str(l.get("league_name") or ""),
            "league_type": str(l.get("league_type_name") or ""),
            "start_time": str(l.get("start_time") or ""),
            "end_time": str(l.get("end_time") or ""),
            "status": int(l.get("status") or 0),
        }
        for l in res
        if isinstance(l, dict) and str(l.get("league_id", "")).isdigit()
    ]
    leagues.sort(key=lambda x: x["league_id"])
    if leagues:
        jdump_if_changed(path, leagues)
    return leagues


def fetch_schedule(league_id: str):
    path = HIST / league_id / "schedule.json"
    cached = jload(path)
    if cached is not None:
        # 联赛有未结束的场次时强制重拉（比分/状态实时变化）
        unfinished = any(int(m.get("status") or 0) != 2 for m in cached if isinstance(m, dict))
        if not unfinished:
            return cached
    d = api(BASE_URL_LEAGUE, {"league_id": league_id})
    matches = (d or {}).get("results") or []
    if not matches:
        return None
    jdump_if_changed(path, matches)
    return matches


def fetch_match(league_id: str, match: dict):
    mid = str(match.get("match_id") or "")
    if not mid:
        return None
    path = HIST / league_id / "matches" / f"{mid}.json"
    import datetime as _dt
    _today = _dt.date.today().isoformat()
    _is_today = str(match.get("start_time") or "")[:10] == _today
    _live = int(match.get("status") or 0) == 1
    if jload(path) is not None and not _is_today and not _live:
        with _lock:
            _stats["matches_skip"] += 1
        return path
    d = api(BASE_URL_MATCH, {"match_id": mid})
    battle_list = (d or {}).get("results") or []
    details = []
    for b in battle_list:
        bid = str(b.get("battle_id") or "")
        if not bid:
            continue
        d2 = api(BASE_URL_BATTLE, {"battle_id": bid}, timeout=12)
        det = (d2 or {}).get("results") or (d2 or {}).get("data")
        if isinstance(det, list) and det:
            det = det[0]
        if not isinstance(det, dict):
            det = {"battle_id": bid, "status": b.get("status"), "win_camp": b.get("win_camp"),
                   "game_duration": b.get("game_duration"), "battle_seq": b.get("battle_seq")}
        details.append(det)
        time.sleep(0.05)
    jdump(path, {"match": match, "battles": details})
    with _lock:
        _stats["matches_new"] += 1
        _stats["battles_new"] += len(details)
    return path


def run(league_ids: list[str] | None, jobs: int) -> None:
    leagues = get_leagues()
    if league_ids:
        want = {str(x) for x in league_ids}
        leagues = [l for l in leagues if l["league_id"] in want]
    print(f"leagues: {len(leagues)}")
    t0 = time.time()
    for i, lg in enumerate(leagues):
        lid = lg["league_id"]
        schedule = fetch_schedule(lid)
        if not schedule:
            print(f"[{i+1}/{len(leagues)}] {lid} {lg['league_name']}: 赛程为空，跳过", flush=True)
            continue
        finished = [m for m in schedule if int(m.get("status") or 0) == 2 or m.get("win_camp")]
        lg_t0 = time.time()
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futs = [pool.submit(fetch_match, lid, m) for m in schedule if m.get("match_id")]
            for _ in as_completed(futs):
                pass
        print(
            f"[{i+1}/{len(leagues)}] {lid} {lg['league_name']}: {len(schedule)} 场（已结束 {len(finished)}）"
            f" 用时 {time.time()-lg_t0:.0f}s | 累计新增 {_stats['matches_new']} 场 / "
            f"{_stats['battles_new']} 局 | 跳过 {_stats['matches_skip']} | 失败 {_stats['errors']}",
            flush=True,
        )
    print(f"\ndone in {time.time()-t0:.0f}s | requests={_stats['requests']} "
          f"new_matches={_stats['matches_new']} new_battles={_stats['battles_new']} "
          f"skipped={_stats['matches_skip']} errors={_stats['errors']}")


def summary() -> None:
    leagues = get_leagues()
    total_m, total_b, total_players = 0, 0, 0
    for lg in leagues:
        lid = lg["league_id"]
        sch = jload(HIST / lid / "schedule.json") or []
        mdir = HIST / lid / "matches"
        files = list(mdir.glob("*.json")) if mdir.exists() else []
        bcnt = 0
        for f in files:
            obj = jload(f) or {}
            bcnt += len(obj.get("battles") or [])
        total_m += len(files)
        total_b += bcnt
        print(f"{lid} {lg['league_name']}: 赛程 {len(sch)} 场 | 已存档 {len(files)} 场 | {bcnt} 局")
    print(f"\nTOTAL: {total_m} 场大场 / {total_b} 局")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", nargs="*", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()
    if args.summary:
        summary()
        return
    if args.all or args.leagues:
        run(args.leagues, args.jobs)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
