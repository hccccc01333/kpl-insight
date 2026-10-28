# -*- coding: utf-8 -*-
"""Read a finished series from the public site's generated assets.

V1 deliberately uses one adapter: the site's official schedule / game-detail /
replay packages. External users can point --site-dir at their own copy of the
same public assets, or use a synthetic fixture with the same schema.

No raw data is redistributed by this module.
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

from .models import Frame, Game, Series

DEFAULT_SITE_DIR = Path(
    os.environ.get("KPL_SITE_DIR")
    or (Path(__file__).resolve().parents[1] / "frontend")
)


class SeriesDataError(RuntimeError):
    """Raised when a series cannot be read without inventing data."""


def _load_js(path: Path) -> Any:
    """Read `NAME = <json>;` files used by the static site."""
    if not path.exists():
        raise SeriesDataError(f"缺少数据文件: {path}")
    text = path.read_text(encoding="utf-8")
    eq = text.find("=")
    if eq < 0:
        raise SeriesDataError(f"无法解析 JS 数据文件（缺少 =）: {path}")
    body = text[eq + 1:].strip().rstrip(";").strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SeriesDataError(f"数据文件 JSON 解析失败: {path}: {exc}") from exc


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise SeriesDataError(f"缺少数据文件: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SeriesDataError(f"数据文件 JSON 解析失败: {path}: {exc}") from exc


def _num(value: Any, field: str, game: str) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise SeriesDataError(f"{game}: 字段 {field} 不是数值: {value!r}") from exc
    if not math.isfinite(n):
        raise SeriesDataError(f"{game}: 字段 {field} 不是有限数值: {value!r}")
    return n


def _int(value: Any, field: str, game: str) -> int:
    n = _num(value, field, game)
    if abs(n - round(n)) > 1e-9:
        raise SeriesDataError(f"{game}: 字段 {field} 不是整数: {value!r}")
    return int(round(n))


def _validate_frames(game_id: str, frames: list[Frame]) -> tuple[list[Frame], list[str]]:
    """Return the longest valid prefix plus explicit quarantine warnings.

    A cumulative counter going backwards is not silently dropped: the offending
    frame and everything after it are excluded, and the report records why.
    """
    if not frames:
        return [], []
    valid: list[Frame] = []
    issues: list[str] = []
    last_m = None
    prev_towers = prev_kills = None
    prev_obj = None
    for i, f in enumerate(frames):
        bad = None
        if last_m is not None and f.minute <= last_m:
            bad = f"帧时间未严格递增（{f.minute}′ <= {last_m}′）"
        elif f.p is not None and not (0.0 <= f.p <= 1.0):
            bad = f"胜率越界（{f.p}）"
        elif any(len(arr) != 2 for arr in (f.kills, f.towers, f.objectives)):
            bad = "阵营数组长度错误"
        elif len(f.objectives[0]) != 4 or len(f.objectives[1]) != 4:
            bad = "资源计数不是 4 项"
        elif prev_towers is not None:
            for side in (0, 1):
                if f.towers[side] < prev_towers[side]:
                    bad = f"推塔累计回退（阵营 {side + 1}：{prev_towers[side]} → {f.towers[side]}）"
                    break
                if f.kills[side] < prev_kills[side]:
                    bad = f"击杀累计回退（阵营 {side + 1}：{prev_kills[side]} → {f.kills[side]}）"
                    break
                if any(f.objectives[side][k] < prev_obj[side][k] for k in range(4)):
                    bad = f"资源累计回退（阵营 {side + 1}）"
                    break
        if bad:
            issues.append(f"{game_id}: 第 {i + 1} 帧 {f.minute}′ 异常「{bad}」；该帧及之后帧已隔离，"
                          f"分析只使用此前 {len(valid)} 帧")
            break
        valid.append(f)
        last_m = f.minute
        prev_towers, prev_kills, prev_obj = f.towers, f.kills, f.objectives
    return valid, issues

def _parse_frames(game_id: str, raw_frames: list[dict]) -> tuple[list[Frame], list[str]]:
    frames: list[Frame] = []
    for i, row in enumerate(raw_frames or []):
        try:
            minute = _num(row.get("m"), "m", game_id)
            kills = [int(v) for v in (row.get("k") or [0, 0])]
            towers = [int(v) for v in (row.get("t") or [0, 0])]
            objectives = [
                [int(v) for v in (row.get("o") or [[], []])[0]],
                [int(v) for v in (row.get("o") or [[], []])[1]],
            ]
            p = None
            if row.get("p") is not None:
                p = _num(row.get("p"), "p", game_id)
            gd = _num(row.get("gd", 0), "gd", game_id)
        except (TypeError, ValueError, IndexError) as exc:
            raise SeriesDataError(f"{game_id}: 第 {i} 帧字段无法解析") from exc
        frames.append(Frame(minute=minute, p=p, gold_diff=gd, kills=kills, towers=towers,
                            objectives=objectives, raw=row))
    return _validate_frames(game_id, frames)


def _parse_bp(game_id: str, bp: Any) -> tuple[list[list], list[str]]:
    warnings: list[str] = []
    if not bp:
        return [], [f"{game_id}: 缺少 BP"]
    if not isinstance(bp, list):
        raise SeriesDataError(f"{game_id}: BP 不是列表")
    picks = 0
    for i, row in enumerate(bp):
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            raise SeriesDataError(f"{game_id}: BP 第 {i} 项格式错误")
        side, kind, hero = row[0], row[1], row[2]
        if side not in (1, 2) or kind not in (0, 1) or not str(hero).strip():
            raise SeriesDataError(f"{game_id}: BP 第 {i} 项非法: {row!r}")
        picks += int(kind == 1)
    if picks != 10:
        warnings.append(f"{game_id}: BP pick 数为 {picks}，预期 10（不补造）")
    return [[int(r[0]), int(r[1]), str(r[2])] for r in bp], warnings


def _game_from_detail(
    series_teams: tuple[str, str],
    match_id: str,
    battle_id: str,
    index_row: list,
    detail: dict,
    replay_battle: dict | None,
) -> Game:
    if not isinstance(detail, dict):
        raise SeriesDataError(f"{match_id}/{battle_id}: 缺少逐局详情对象")
    if str(detail.get("match")) != str(match_id):
        raise SeriesDataError(f"{battle_id}: detail.match={detail.get('match')} != {match_id}")
    seq = _int(detail.get("seq"), "seq", battle_id)
    if int(index_row[1]) != seq:
        raise SeriesDataError(f"{battle_id}: 局号不一致（索引 {index_row[1]} / 详情 {seq}）")
    t1, t2 = str(detail.get("t1") or ""), str(detail.get("t2") or "")
    if not t1 or not t2:
        raise SeriesDataError(f"{battle_id}: 缺少战队名")
    if {t1, t2} != set(series_teams):
        raise SeriesDataError(f"{battle_id}: 战队 {t1}/{t2} 不属于系列赛 {series_teams}")
    win = _int(detail.get("win"), "win", battle_id)
    if win not in (1, 2):
        raise SeriesDataError(f"{battle_id}: 未结算 win={win}")
    winner = t1 if win == 1 else t2
    win_team = str(index_row[4] or "")
    if win_team and win_team != winner:
        raise SeriesDataError(f"{battle_id}: 索引胜方 {win_team} != 详情胜方 {winner}")
    duration = _num(detail.get("dur"), "dur", battle_id)

    frames: list[Frame] = []
    events: list[dict] = []
    warnings: list[str] = []
    raw_frame_count = 0
    if replay_battle:
        if replay_battle.get("battleId") not in (None, battle_id):
            raise SeriesDataError(f"{battle_id}: replay battleId 不一致")
        if replay_battle.get("t1") and replay_battle.get("t1") != t1:
            raise SeriesDataError(f"{battle_id}: replay/detail 战队顺序不一致")
        raw_frames = replay_battle.get("frames") or []
        raw_frame_count = len(raw_frames)
        frames, frame_warnings = _parse_frames(battle_id, raw_frames)
        warnings.extend(frame_warnings)
        events = list(replay_battle.get("events") or [])
        if not frames:
            warnings.append(f"{battle_id}: 没有可用分钟快照")
        elif len(frames) < 3:
            warnings.append(f"{battle_id}: 可用分钟快照仅 {len(frames)} 帧")
    else:
        warnings.append(f"{battle_id}: 缺少复盘时间轴（只有逐局详情）")

    bp, bp_warn = _parse_bp(battle_id, detail.get("bp"))
    warnings.extend(bp_warn)
    players = list(detail.get("players") or [])
    if len(players) != 10:
        warnings.append(f"{battle_id}: 选手行数为 {len(players)}，预期 10")

    return Game(
        battle_id=battle_id,
        seq=seq,
        team1=t1,
        team2=t2,
        winner=winner,
        duration=duration,
        kills=[_int(detail.get("k1", 0), "k1", battle_id), _int(detail.get("k2", 0), "k2", battle_id)],
        gold=[_int(detail.get("g1", 0), "g1", battle_id), _int(detail.get("g2", 0), "g2", battle_id)],
        bp=bp,
        players=players,
        frames=frames,
        events=events,
        warnings=warnings,
        frames_total=raw_frame_count,
        quarantined_frames=max(0, raw_frame_count - len(frames)),
    )


def load_series(match_id: str, site_dir: str | Path | None = None) -> Series:
    """Load a finished series and validate its orientation / core fields."""
    match_id = str(match_id)
    root = Path(site_dir) if site_dir else DEFAULT_SITE_DIR
    assets = root / "assets"
    schedule = _load_js(assets / "schedule_all.js")
    row = next((r for r in schedule if str(r.get("matchId")) == match_id), None)
    if not row:
        raise SeriesDataError(f"赛程中找不到 {match_id}")
    if not row.get("done") or int(row.get("st") or 0) != 2:
        raise SeriesDataError(f"{match_id}: 系列赛未结束，不能生成赛后诊断")

    game_index_all = _load_js(assets / "games" / "index.js")
    gi = game_index_all.get(match_id)
    if not gi or not gi.get("b"):
        raise SeriesDataError(f"{match_id}: 缺少逐局索引")
    league_id = str(row.get("leagueId") or gi.get("lg") or "")
    detail_path = assets / "games" / f"{league_id}.json"
    detail_all = _load_json(detail_path)
    replay_path = assets / "replay" / f"{match_id}.json"
    replay = _load_json(replay_path) if replay_path.exists() else {}

    team1, team2 = str(row["team1"]), str(row["team2"])
    replay_battles = {str(b.get("battleId")): b for b in (replay.get("battles") or [])}
    games: list[Game] = []
    warnings: list[str] = []
    if not replay:
        warnings.append(f"{match_id}: 缺少分钟级复盘包（逐局只看比分/BP/选手）")
    for idx_row in gi["b"]:
        bid = str(idx_row[0])
        detail = detail_all.get(bid)
        if not detail:
            raise SeriesDataError(f"{match_id}: 缺少逐局详情 {bid}")
        games.append(_game_from_detail((team1, team2), match_id, bid, idx_row, detail,
                                        replay_battles.get(bid)))
    games.sort(key=lambda g: g.seq)
    if len(games) != len(gi["b"]):
        raise SeriesDataError(f"{match_id}: 逐局数量不一致")

    score1 = _int(row.get("score1"), "score1", match_id)
    score2 = _int(row.get("score2"), "score2", match_id)
    wins1 = sum(1 for g in games if g.winner == team1)
    wins2 = sum(1 for g in games if g.winner == team2)
    if (wins1, wins2) != (score1, score2):
        raise SeriesDataError(
            f"{match_id}: 大场比分 {score1}:{score2} 与逐局胜方汇总 {wins1}:{wins2} 不一致"
        )
    if score1 + score2 != len(games):
        raise SeriesDataError(f"{match_id}: 已结束系列赛局数 {len(games)} != 比分和 {score1 + score2}")
    bo = _int(row.get("bo"), "bo", match_id)
    if len(games) > bo:
        raise SeriesDataError(f"{match_id}: 局数 {len(games)} 超过 BO{bo}")

    for g in games:
        warnings.extend(g.warnings)
    return Series(
        match_id=match_id,
        date=str(row.get("date") or ""),
        league_id=league_id,
        league_name=str(row.get("leagueName") or ""),
        stage=str(row.get("stage") or ""),
        bo=bo,
        team1=team1,
        team2=team2,
        score1=score1,
        score2=score2,
        games=games,
        warnings=warnings,
        source=str(root),
    )
