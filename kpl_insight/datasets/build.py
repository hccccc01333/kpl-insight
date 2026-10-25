"""
构建 KPL 历史赛事分析数据集

输入：
- data/realtime/schedule_archive.csv
- data/realtime/raw_snapshots/{battle_id}/*.json

输出：
- data/analysis/matches.parquet / .csv
- data/analysis/battles.parquet / .csv
- data/analysis/teams.parquet / .csv
- data/analysis/events.parquet / .csv

运行：
    python -m kpl_insight.datasets.build
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import pandas as pd

from kpl_insight.core import (
    POSITIONS,
    PROJECT_ROOT,
    ScheduleCenter,
    detect_events,
    load_battle_jsons,
    load_battle_players,
)

# raw payload 里的 position_key（英文）→ 官方数字编码（训练脚本按数字分路聚合）
POS_KEY_TO_ID = {v: k for k, v in POSITIONS.items()}


ANALYSIS_DIR = PROJECT_ROOT / "data" / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def save_table(df: pd.DataFrame, name: str):
    csv_path = ANALYSIS_DIR / f"{name}.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    try:
        df.to_parquet(ANALYSIS_DIR / f"{name}.parquet", index=False)
    except Exception:
        pass
    print(f"{name}: {len(df)} rows -> {csv_path}")


def latest_final_snapshot(snapshots: list[dict]) -> dict | None:
    if not snapshots:
        return None
    finals = [s for s in snapshots if int(s.get("status", 0) or 0) == 2]
    return finals[-1] if finals else snapshots[-1]


def build():
    center = ScheduleCenter()
    archive = center.load_schedule_archive()
    raw_root = PROJECT_ROOT / "data" / "realtime" / "raw_snapshots"

    match_rows = []
    battle_rows = []
    team_rows = []
    event_rows = []
    player_rows = []
    training_rows = []

    # 选手/战队图标：payload 不含 icon 字段，按名称从既有 players 表继承（缺失留空）
    player_icon_map: dict[str, str] = {}
    team_icon_map: dict[str, str] = {}
    old_players_path = PROCESSED_DIR / "players.csv"
    if old_players_path.exists():
        try:
            _old = pd.read_csv(old_players_path)
            if "player_icon" in _old.columns:
                player_icon_map = dict(zip(_old["player_name"].astype(str), _old["player_icon"].fillna("").astype(str)))
            if "team_icon" in _old.columns:
                team_icon_map = dict(zip(_old["team_name"].astype(str), _old["team_icon"].fillna("").astype(str)))
            print(f"inherited icons: players={len(player_icon_map)} teams={len(team_icon_map)}")
        except (OSError, pd.errors.ParserError):
            pass

    if archive.empty:
        raise RuntimeError("schedule archive 为空，请先运行 build_schedule_archive.py")

    for _, match in archive.iterrows():
        battle_ids = [x for x in str(match.get("battle_ids", "")).split("|") if x]
        match_rows.append(
            {
                "league_id": match.get("league_id"),
                "match_id": match.get("match_id"),
                "date": match.get("date"),
                "start_time": match.get("start_time"),
                "team1": match.get("team1"),
                "team2": match.get("team2"),
                "stage": match.get("stage"),
                "bo_type": match.get("bo_type"),
                "scheduled_battles": len(battle_ids),
                "has_raw": int(any((raw_root / bid).exists() for bid in battle_ids)),
            }
        )

        for seq, battle_id in enumerate(battle_ids, 1):
            battle_dir = raw_root / battle_id
            if not battle_dir.exists():
                continue
            snapshots = load_battle_jsons(battle_dir)
            final = latest_final_snapshot(snapshots)
            if not final:
                continue

            c1 = final.get("camp1_team", "")
            c2 = final.get("camp2_team", "")
            win_camp = int(final.get("win_camp", 0) or 0)
            winner = c1 if win_camp == 1 else c2 if win_camp == 2 else ""
            if win_camp in (1, 2):
                training_row = {
                    "battle_id": battle_id,
                    "match_id": match.get("match_id"),
                    "league_id": match.get("league_id"),
                    "game_duration": int(final.get("time_sec", 0)) * 1000,
                    "win_camp": win_camp,
                    "status": final.get("status", 0),
                }
                for camp in (1, 2):
                    prefix = f"camp{camp}"
                    training_row[f"{prefix}_team_name"] = final.get(f"{prefix}_team", "")
                    for target, source in {
                        "gold": "gold", "kill_num": "kill", "assist_num": "assist",
                        "death_num": "death", "push_tower_num": "tower",
                        "kill_tyrant_num": "tyrant", "kill_dark_tyrant_num": "dark_tyrant",
                        "kill_big_dragon_num": "lord", "kill_prophet_dragon_num": "prophet",
                        "kill_shadow_dragon_num": "shadow", "kill_storm_dragon_king_num": "storm",
                    }.items():
                        training_row[f"{prefix}_{target}"] = final.get(f"{prefix}_{source}", 0)
                training_rows.append(training_row)
            duration_min = final.get("minute", 0)
            camp1_gold = final.get("camp1_gold", 0)
            camp2_gold = final.get("camp2_gold", 0)
            camp1_kill = final.get("camp1_kill", 0)
            camp2_kill = final.get("camp2_kill", 0)
            camp1_tower = final.get("camp1_tower", 0)
            camp2_tower = final.get("camp2_tower", 0)
            camp1_objectives = final.get("camp1_tyrant", 0) + final.get("camp1_dark_tyrant", 0) + final.get("camp1_lord", 0) + final.get("camp1_storm", 0)
            camp2_objectives = final.get("camp2_tyrant", 0) + final.get("camp2_dark_tyrant", 0) + final.get("camp2_lord", 0) + final.get("camp2_storm", 0)

            battle_rows.append(
                {
                    "league_id": match.get("league_id"),
                    "match_id": match.get("match_id"),
                    "battle_id": battle_id,
                    "date": match.get("date"),
                    "game_no": seq,
                    "team1": c1,
                    "team2": c2,
                    "winner": winner,
                    "duration_min": duration_min,
                    "snapshot_count": len(snapshots),
                    "has_timeline": len({int(s.get("minute", 0)) for s in snapshots}) > 3,
                    "gold_diff": camp1_gold - camp2_gold,
                    "kill_diff": camp1_kill - camp2_kill,
                    "tower_diff": camp1_tower - camp2_tower,
                    "objective_diff": camp1_objectives - camp2_objectives,
                    "total_kills": camp1_kill + camp2_kill,
                    "total_towers": camp1_tower + camp2_tower,
                }
            )

            for camp, team, opp in [(1, c1, c2), (2, c2, c1)]:
                p = f"camp{camp}"
                q = "camp2" if camp == 1 else "camp1"
                team_rows.append(
                    {
                        "league_id": match.get("league_id"),
                        "match_id": match.get("match_id"),
                        "battle_id": battle_id,
                        "date": match.get("date"),
                        "game_no": seq,
                        "team": team,
                        "opponent": opp,
                        "win": int(team == winner) if winner else float("nan"),
                        "duration_min": duration_min,
                        "gold": final.get(f"{p}_gold", 0),
                        "gold_diff": final.get(f"{p}_gold", 0) - final.get(f"{q}_gold", 0),
                        "kills": final.get(f"{p}_kill", 0),
                        "kill_diff": final.get(f"{p}_kill", 0) - final.get(f"{q}_kill", 0),
                        "towers": final.get(f"{p}_tower", 0),
                        "tower_diff": final.get(f"{p}_tower", 0) - final.get(f"{q}_tower", 0),
                        "objectives": final.get(f"{p}_tyrant", 0) + final.get(f"{p}_dark_tyrant", 0) + final.get(f"{p}_lord", 0) + final.get(f"{p}_storm", 0),
                    }
                )

            players_payload = load_battle_players(battle_id)
            for p in players_payload.get("players") or []:
                kill = int(p.get("kill_num") or 0)
                death = int(p.get("death_num") or 0)
                assist = int(p.get("assist_num") or 0)
                pname = str(p.get("player_name") or "")
                tname = str(p.get("team_name") or "")
                player_rows.append(
                    {
                        "league_id": match.get("league_id"),
                        "match_id": match.get("match_id"),
                        "battle_id": battle_id,
                        "date": match.get("date"),
                        "game_no": seq,
                        "team_id": p.get("team_id"),
                        "team_name": tname,
                        "team_icon": team_icon_map.get(tname, ""),
                        "player_name": pname,
                        "player_icon": player_icon_map.get(pname, ""),
                        "hero_id": p.get("hero_id"),
                        "hero_name": p.get("hero_name"),
                        "hero_icon": p.get("hero_icon"),
                        "camp": p.get("camp"),
                        # position 是训练脚本聚合分路用的数字编码；position_desc 给前端展示。
                        # 只写 desc 会让 train_realtime_model_v9 直接 KeyError（2026-10 踩过）。
                        "position": POS_KEY_TO_ID.get(str(p.get("position_key") or "").strip()),
                        "position_desc": p.get("position_name"),
                        "kill_num": kill,
                        "death_num": death,
                        "assist_num": assist,
                        "kda": (kill + assist) / death if death else float(kill + assist),
                        "gold": p.get("gold"),
                        "participation_rate": p.get("participation_rate"),
                        # 训练侧算 hurt_conc_diff 用的是总量，不是占比，两个都要留
                        "hurt_to_hero_total": p.get("hurt_to_hero_total"),
                        "be_hurt_by_hero_total": p.get("be_hurt_by_hero_total"),
                        "hurt_to_hero_total_rate": p.get("hurt_to_hero_total_rate"),
                        "be_hurt_by_hero_total_rate": p.get("be_hurt_by_hero_total_rate"),
                        "mvp_score": p.get("mvp_score"),
                        "is_mvp": int(p.get("is_mvp") or 0),
                        "is_lose_mvp": int(p.get("is_lose_mvp") or 0),
                    }
                )

            for event in detect_events(snapshots):
                event_rows.append(
                    {
                        "league_id": match.get("league_id"),
                        "match_id": match.get("match_id"),
                        "battle_id": battle_id,
                        "date": match.get("date"),
                        "game_no": seq,
                        **event,
                    }
                )

    save_table(pd.DataFrame(match_rows), "matches")
    save_table(pd.DataFrame(battle_rows), "battles")
    save_table(pd.DataFrame(team_rows), "teams")
    save_table(pd.DataFrame(event_rows), "events")
    if training_rows:
        training_path = PROCESSED_DIR / "battles.csv"
        pd.DataFrame(training_rows).to_csv(training_path, index=False, encoding="utf-8-sig")
        print(f"training battles: {len(training_rows)} rows -> {training_path}")
    if player_rows:
        pl_path = PROCESSED_DIR / "players.csv"
        pd.DataFrame(player_rows).to_csv(pl_path, index=False, encoding="utf-8-sig")
        print(f"players: {len(player_rows)} rows -> {pl_path}")


def main():
    parser = argparse.ArgumentParser(description="Build analysis and training tables from local schedule and snapshots")
    parser.parse_args()
    build()


if __name__ == "__main__":
    main()
