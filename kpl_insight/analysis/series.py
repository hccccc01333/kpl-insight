# -*- coding: utf-8 -*-
"""Series Intelligence V1 analysis.

Design rule: only facts with a frame/detail reference, or explicitly labelled
statistical inference / unverified hypothesis, are allowed in the report.
No coaching-intent or causal claims.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import Frame, Game, Series

SCHEMA_VERSION = "1.0"
CHECKPOINTS = (5.0, 8.0, 10.0, 15.0)
OBJECTIVE_NAMES = ("暴君", "黑暗暴君", "主宰", "风暴龙王")


def _r(v: float | None, n: int = 0) -> float | None:
    return None if v is None else round(float(v), n)


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def _signed(v: float | None, n: int = 0) -> str:
    if v is None:
        return "—"
    return f"{v:+.{n}f}"


def _team_gold(game: Game, frame: Frame, team: str) -> float | None:
    return game.gold_for(frame, team)


def _event_text(events: list[dict]) -> list[str]:
    return [str(e.get("l") or "") for e in events if e.get("l")]


def _events_near(game: Game, m0: float, m1: float, pad: float = 1.0) -> list[str]:
    out = []
    for e in game.events:
        try:
            m = float(e.get("m"))
        except (TypeError, ValueError):
            continue
        if m0 - pad <= m <= m1 + pad and e.get("l"):
            out.append(str(e["l"]))
    return list(dict.fromkeys(out))[:4]


def _window_segments(game: Game, team: str) -> list[dict]:
    """Consecutive p-runs for `team`; if no p, gold-diff runs are a proxy."""
    fr = game.frames
    if len(fr) < 2:
        return []
    has_p = sum(1 for f in fr if f.p is not None) >= 3
    segs: list[dict] = []
    cur: dict | None = None
    use_p = has_p
    for i in range(1, len(fr)):
        a, b = fr[i - 1], fr[i]
        if use_p:
            va, vb = game.p_for(a, team), game.p_for(b, team)
        else:
            va, vb = game.gold_for(a, team), game.gold_for(b, team)
            if va is not None and vb is not None:
                va, vb = va / 1000.0, vb / 1000.0
        if va is None or vb is None:
            if cur:
                segs.append(cur); cur = None
            continue
        d = vb - va
        if abs(d) < (0.01 if use_p else 0.10):
            continue
        dr = 1 if d > 0 else -1
        if cur and cur["dir"] == dr:
            cur["to"] = vb; cur["end"] = i; cur["mag"] = abs(vb - cur["from"])
        else:
            if cur:
                segs.append(cur)
            cur = {"dir": dr, "from": va, "to": vb, "start": i - 1, "end": i,
                   "mag": abs(d), "kind": "model_probability" if use_p else "gold_proxy"}
    if cur:
        segs.append(cur)
    # 太短的噪声段不进入报告
    segs = [s for s in segs if fr[s["end"]].minute - fr[s["start"]].minute >= 1.0 or s["mag"] >= (0.06 if use_p else 0.4)]
    for s in segs:
        s["m0"] = fr[s["start"]].minute
        s["m1"] = fr[s["end"]].minute
        s["favored"] = team if s["dir"] > 0 else game.opposite(team)
        s["p0"] = _r(game.p_for(fr[s["start"]], s["favored"]) if use_p else None, 3)
        s["p1"] = _r(game.p_for(fr[s["end"]], s["favored"]) if use_p else None, 3)
        s["g0"] = _r(game.gold_for(fr[s["start"]], s["favored"]))
        s["g1"] = _r(game.gold_for(fr[s["end"]], s["favored"]))
    return segs


def _windows(game: Game) -> dict:
    """Three candidate windows for the actual winner; never a causal verdict."""
    winner = game.winner
    segs = _window_segments(game, winner)
    final_p = None
    if game.frames:
        final_p = game.p_for(game.frames[-1], winner)
    final_agree = final_p is not None and final_p >= 0.5
    # 只有对胜方方向有利的窗口才标 key；否则只列摆动
    favorable = [s for s in segs if s["favored"] == winner]
    key = max(favorable, key=lambda s: s["mag"]) if favorable else None
    top = sorted(segs, key=lambda s: s["mag"], reverse=True)[:3]
    if key and key not in top:
        top[-1] = key
    top.sort(key=lambda s: s["m0"])
    out = []
    for s in top:
        ev = _events_near(game, s["m0"], s["m1"], 1.0)
        out.append({
            "start_minute": _r(s["m0"], 1),
            "end_minute": _r(s["m1"], 1),
            "kind": s["kind"],
            "favored_team": s["favored"],
            "from_value": s["p0"] if s["kind"] == "model_probability" else s["g0"],
            "to_value": s["p1"] if s["kind"] == "model_probability" else s["g1"],
            "delta": _r((s["p1"] - s["p0"]) if s["kind"] == "model_probability" else (s["g1"] - s["g0"]),
                        3 if s["kind"] == "model_probability" else 0),
            "unit": "probability" if s["kind"] == "model_probability" else "gold",
            "events": ev,
            "evidence_level": "estimate" if s["kind"] == "model_probability" else "proxy",
            "key": bool(key is s),
        })
    return {
        "model_last_valid_prob_for_winner": _r(final_p, 3),
        "model_last_valid_agrees_with_winner": bool(final_agree) if final_p is not None else None,
        "last_valid_minute": _r(game.frames[-1].minute, 1) if game.frames else None,
        "quarantined_frames": game.quarantined_frames,
        "candidates": out,
        "note": "窗口是同类数据上的候选变化段，不是因果结论；没有直播胜率时只使用金差代理。",
    }


def _bp_summary(series: Series) -> dict:
    picks_by_team: dict[str, list[str]] = {series.team1: [], series.team2: []}
    bans_by_team: dict[str, list[str]] = {series.team1: [], series.team2: []}
    per_game = []
    for g in series.games:
        picks1, picks2, bans1, bans2 = [], [], [], []
        for side, kind, hero in g.bp:
            team = g.team1 if side == 1 else g.team2
            if kind == 1:
                (picks1 if team == g.team1 else picks2).append(hero)
                picks_by_team[team].append(hero)
            else:
                (bans1 if team == g.team1 else bans2).append(hero)
                bans_by_team[team].append(hero)
        per_game.append({
            "seq": g.seq, "team1": g.team1, "team2": g.team2,
            "picks1": picks1, "picks2": picks2, "bans1": bans1, "bans2": bans2,
        })
    all_picks = [p for g in per_game for p in g["picks1"] + g["picks2"]]
    counts: dict[str, int] = {}
    for p in all_picks:
        counts[p] = counts.get(p, 0) + 1
    common = sorted(((h, n) for h, n in counts.items() if n >= 2), key=lambda x: (-x[1], x[0]))
    return {
        "per_game": per_game,
        "picks_by_team": picks_by_team,
        "bans_by_team": bans_by_team,
        "common_picks": [{"hero": h, "games": n} for h, n in common],
    }


def _game_summary(series: Series, game: Game) -> dict:
    checkpoints = {}
    winner = game.winner
    for target in CHECKPOINTS:
        after = [x for x in game.frames if x.minute >= target] if game.frames else []
        f = min(after, key=lambda x: x.minute) if after else (game.frames[-1] if game.frames else None)
        if f and abs(f.minute - target) <= 2.0:
            checkpoints[str(int(target))] = {
                "actual_minute": _r(f.minute, 1),
                "gold_diff_series_team1": _r(game.gold_for(f, series.team1)),
                "gold_diff_winner": _r(game.gold_for(f, winner)),
            }
        else:
            checkpoints[str(int(target))] = {
                "actual_minute": _r(f.minute, 1) if f else None,
                "gold_diff_series_team1": None,
                "gold_diff_winner": None,
                "note": "最近帧距离目标超过 2 分钟，不补造检查点",
            }
    last = game.final_frame()
    early = game.early_frame(8.0)
    early_leader = None
    if early is not None:
        gd = game.gold_for(early, series.team1)
        if gd is not None and abs(gd) >= 1:
            early_leader = series.team1 if gd > 0 else series.team2
    final_stats = {}
    if last:
        # 击杀/总经济用逐局详情（完整局），推塔/资源只能用最后一个通过校验的帧；
        # 末帧累计回退时不假装它是 final。
        final_gold_diff = (game.gold[0] - game.gold[1]) if game.team1 == series.team1 else (game.gold[1] - game.gold[0])
        final_stats = {
            "kills": {"team1": game.kills[0], "team2": game.kills[1]},
            "gold": {"team1": game.gold[0], "team2": game.gold[1]},
            "towers_last_valid": {"team1": last.towers[0], "team2": last.towers[1]},
            "objectives_last_valid": {
                "team1": dict(zip(OBJECTIVE_NAMES, last.objectives[0])),
                "team2": dict(zip(OBJECTIVE_NAMES, last.objectives[1])),
            },
            "gold_diff_series_team1": _r(final_gold_diff),
            "last_valid_minute": _r(last.minute, 1),
            "is_full_game": game.quarantined_frames == 0,
            "quarantined_frames": game.quarantined_frames,
        }
    return {
        "seq": game.seq,
        "battle_id": game.battle_id,
        "team1": game.team1,
        "team2": game.team2,
        "winner": winner,
        "winner_side": game.side_of(winner),
        "duration": _r(game.duration, 1),
        "kills": {"team1": game.kills[0], "team2": game.kills[1]},
        "gold": {"team1": game.gold[0], "team2": game.gold[1]},
        "early_leader": early_leader,
        "comeback": bool(early_leader and early_leader != winner),
        "checkpoints": checkpoints,
        "final": final_stats,
        "coverage": {
            "frames": len(game.frames),
            "frames_total": game.frames_total or len(game.frames),
            "quarantined_frames": game.quarantined_frames,
            "bp_actions": len(game.bp),
            "players": len(game.players),
            "has_minute_data": bool(game.frames),
            "has_bp": bool(game.bp),
        },
        "windows": _windows(game),
    }


def _series_comparison(series: Series, game_rows: list[dict]) -> dict:
    winner = series.team1 if series.score1 > series.score2 else series.team2
    early_positive = []
    for g, row in zip(series.games, game_rows):
        cp = row["checkpoints"].get("8") or {}
        gd = cp.get("gold_diff_series_team1")
        if gd is not None:
            early_positive.append((g.seq, gd, gd > 0))
    comebacks = [g.seq for g, row in zip(series.games, game_rows) if row["comeback"]]
    durations = [g.duration for g in series.games]
    objective_games = [g for g in series.games if g.final_frame() is not None]
    objectives = None
    if objective_games:
        objectives = {series.team1: {n: 0 for n in OBJECTIVE_NAMES},
                      series.team2: {n: 0 for n in OBJECTIVE_NAMES}}
        for g in objective_games:
            last = g.final_frame()
            for side_idx, team in ((0, g.team1), (1, g.team2)):
                for i, name in enumerate(OBJECTIVE_NAMES):
                    objectives[team][name] += last.objectives[side_idx][i]
    return {
        "winner": winner,
        "comeback_games": comebacks,
        "early_8min_positive_for_series_team1": [
            {"seq": seq, "gold_diff": _r(gd), "positive": pos} for seq, gd, pos in early_positive
        ],
        "durations": {"min": _r(min(durations), 1), "max": _r(max(durations), 1),
                      "avg": _r(sum(durations) / len(durations), 1)},
        "objective_totals": objectives,
        "objective_games": len(objective_games),
        "side_sequence": [
            {"seq": g.seq, "team1_side": g.side_of(series.team1),
             "team2_side": g.side_of(series.team2), "winner_side": g.side_of(g.winner)}
            for g in series.games
        ],
    }


def _claims(series: Series, game_rows: list[dict], comparison: dict, bp: dict) -> dict:
    winner = comparison["winner"]
    loser = series.team2 if winner == series.team1 else series.team1
    n = len(series.games)
    with_frames = sum(1 for r in game_rows if r["coverage"]["has_minute_data"])
    with_bp = sum(1 for r in game_rows if r["coverage"]["has_bp"])
    comeback = comparison["comeback_games"]
    early_positive = [x for x in comparison["early_8min_positive_for_series_team1"] if x["positive"]]
    facts = [
        {"text": f"{winner} {max(series.score1, series.score2)}:{min(series.score1, series.score2)} {loser}，"
                 f"共 {n} 局，BO{series.bo}。", "evidence": [{"type": "official_schedule", "match_id": series.match_id}]},
        {"text": f"{with_frames}/{n} 局有分钟级快照，{with_bp}/{n} 局有 BP 记录。",
         "evidence": [{"type": "game_details", "battle_id": g.battle_id} for g in series.games]},
    ]
    for row in game_rows:
        if row["comeback"]:
            facts.append({
                "text": f"G{row['seq']}：8 分钟前后领先的是 {row['early_leader']}，最终胜方是 {row['winner']}。",
                "evidence": [{"type": "frame", "battle_id": row["battle_id"], "minute": 8,
                              "field": "gold_diff"}],
            })
    inferences = []
    if early_positive:
        inferences.append({
            "text": f"{series.team1} 在 {len(early_positive)}/{n} 局的 8 分钟金差为正；"
                    f"其中 G1 的早期领先方最终落败。" if 1 in [x["seq"] for x in early_positive] and comeback
                    else f"{series.team1} 在 {len(early_positive)}/{n} 局的 8 分钟金差为正。",
            "level": "statistical_inference",
            "evidence": [{"type": "frame", "battle_id": series.games[i].battle_id, "minute": 8,
                          "field": "gold_diff"} for i in range(n)],
        })
    # objective totals: only state the count if we actually have frames; never fake 0
    objectives = comparison.get("objective_totals")
    if objectives:
        obj_w = objectives.get(winner, {})
        obj_l = objectives.get(loser, {})
        inferences.append({
            "text": f"资源累计（{comparison.get('objective_games', 0)} 局有效末帧求和）：{winner} 暴君/黑暗暴君/主宰/风暴龙王 = "
                    f"{obj_w.get('暴君', 0)}/{obj_w.get('黑暗暴君', 0)}/{obj_w.get('主宰', 0)}/{obj_w.get('风暴龙王', 0)}；"
                    f"{loser} = {obj_l.get('暴君', 0)}/{obj_l.get('黑暗暴君', 0)}/{obj_l.get('主宰', 0)}/{obj_l.get('风暴龙王', 0)}。",
            "level": "descriptive_inference",
            "evidence": [{"type": "frame", "battle_id": g.battle_id, "field": "objectives"} for g in series.games if g.final_frame()],
        })
    hypotheses = []
    if comeback:
        hypotheses.append({
            "text": f"G{comeback[0]} 的早期领先没有转化为胜利；当前报告只能确认金差/资源/事件同段变化，"
                    f"不能证明具体战术或指挥原因。",
            "level": "unverified_hypothesis",
            "evidence": [{"type": "frame", "battle_id": series.games[comeback[0] - 1].battle_id,
                          "note": "候选窗口见该局 windows"}],
        })
    if bp.get("common_picks"):
        hypotheses.append({
            "text": "BP 中存在跨局重复选用的英雄；这只说明选禁序列重合，不能据此判断教练意图或胜负原因。",
            "level": "unverified_hypothesis",
            "evidence": [{"type": "bp", "match_id": series.match_id}],
        })
    return {"facts": facts, "inferences": inferences, "hypotheses": hypotheses}


def analyze_series(series: Series) -> dict:
    game_rows = [_game_summary(series, g) for g in series.games]
    comparison = _series_comparison(series, game_rows)
    bp = _bp_summary(series)
    claims = _claims(series, game_rows, comparison, bp)
    winner = comparison["winner"]
    comebacks = comparison["comeback_games"]
    headline = (
        f"{winner} 以 {max(series.score1, series.score2)}:{min(series.score1, series.score2)} 赢下系列赛；"
        f"{len(series.games)} 局中 {sum(1 for r in game_rows if r['coverage']['has_minute_data'])} 局有分钟级数据。"
        + (f" G{comebacks[0]} 是唯一一局早期领先方与最终胜方不一致。" if len(comebacks) == 1 else
           (f" 早期领先方与最终胜方不一致的局：G{'、G'.join(map(str, comebacks))}。" if comebacks else "四局早期领先方与最终胜方一致。"))
        + (" 数据状态 degraded：末段累计计数异常已隔离。" if series.warnings else "")
    )
    games_with_frames = sum(1 for r in game_rows if r["coverage"]["has_minute_data"])
    games_with_bp = sum(1 for r in game_rows if r["coverage"]["has_bp"])
    status = "ok" if games_with_frames == len(series.games) and games_with_bp == len(series.games) and not series.warnings else "degraded"
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": "kpl-insight-series", "version": "0.2.0"},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "series": {
            "match_id": series.match_id, "date": series.date, "league_id": series.league_id,
            "league_name": series.league_name, "stage": series.stage, "bo": series.bo,
            "team1": series.team1, "team2": series.team2,
            "score1": series.score1, "score2": series.score2,
        },
        "headline": headline,
        "data_quality": {
            "status": status,
            "games": len(series.games),
            "games_with_minute_data": games_with_frames,
            "games_with_bp": games_with_bp,
            "warnings": series.warnings,
        },
        "conclusion": claims,
        "games": game_rows,
        "series_comparison": comparison,
        "bp": bp,
        "limits": [
            "胜率/窗口是模型或金差代理的候选变化段，不是因果结论。",
            "资源/金差/击杀/推塔来自逐帧快照；缺失时不补造。",
            "未使用教练语音、训练赛、选手伤停等外部信息，不能判断指挥责任。",
        ],
    }
