# -*- coding: utf-8 -*-
"""实时数据中心 v2：多指标序列 + 预测归档（胜率/经济/击杀/推塔/选手经济 + 预测-实际对照）。

输出 assets/live.js：
  matches[]  进行中的局（实时）
  today[]    今日场次实时比分
  history[]  最近结束的局（归档：完整指标序列，赛后回看）

用法：
  python build_live_data.py              生成一次
  python build_live_data.py --watch 30   每 30 秒刷新
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kpl_insight.core import (  # noqa: E402
    PROJECT_ROOT,
    _replay_v11_timeline,
    _resolve_battle_snapshot_dir,
    api_get,
    BASE_URL_LEAGUE,
    BASE_URL_MATCH,
    load_battle_jsons,
    load_model,
    RAW_DIR,
)
from kpl_insight.models.display import (  # noqa: E402
    blend_prior,
    build_display,
    calibrate_probability,
    ema_smooth,
    load_calibrator,
    model_fingerprint,
    objective_window,
    prior_weight,
)

SITE = Path(os.environ.get("KPL_SITE_DIR", str(PROJECT_ROOT / "output" / "site"))).expanduser().resolve()
OUT = SITE / "assets" / "live.js"
PRIOR_PATH = PROJECT_ROOT / "data" / "realtime" / "prematch_priors.json"
_MODEL = load_model()
_MODEL_FP = model_fingerprint(_MODEL)
DISPLAY_CALIB = load_calibrator(model_fp=_MODEL_FP)


def load_priors() -> dict:
    try:
        return json.loads(PRIOR_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def prior_for_match(priors: dict, match_id: str, camp1_team: str) -> float | None:
    """把赛前先验转成 camp1 视角；队名对不上时返回 None。"""
    row = priors.get(str(match_id))
    if not row:
        return None
    p = row.get("p_team1")
    if p is None:
        return None
    if str(camp1_team) == str(row.get("team1")):
        return float(p)
    if str(camp1_team) == str(row.get("team2")):
        return 1.0 - float(p)
    return None
# 归档全量留在主项目（211 局、2.5MB 级）；网站只放最近若干局，其余按需走 per-match 分片
HISTORY_PATH = PROJECT_ROOT / "data" / "realtime" / "site_live_history.json"
ARCHIVE_DIR = SITE / "assets" / "live_hist"
RECENT_LEAGUES = ["20260004", "20260003", "20260002"]
MAX_POINTS = 60
HISTORY_KEEP = 10000      # 归档本身不丢：只裁掉极老的局，保证回看得到
LIVE_RECENT = 6           # live.js 内联的最近局数（首屏无需额外请求）


def load_history() -> dict:
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_history(hist: dict) -> None:
    """内容未变时不落盘：该文件被站点监视器监听，每 30 秒无脑重写会触发整站重建风暴。"""
    body = json.dumps(hist, ensure_ascii=False, separators=(",", ":"))
    try:
        if HISTORY_PATH.read_text(encoding="utf-8") == body:
            return
    except OSError:
        pass
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(body, encoding="utf-8")


def write_archive_shards(hist: dict) -> None:
    """按场输出预测复盘分片：assets/live_hist/<matchId>.js

    归档只在 live.js 里内联最近几局，早先的比赛靠这些分片按需加载，
    否则比赛页的「预测复盘」过两天就查不到了。内容未变则不动文件（防提交风暴）。
    """
    by_match: dict[str, list] = {}
    for v in hist.values():
        if not (v.get("pts") or []):
            continue
        by_match.setdefault(str(v.get("matchId") or ""), []).append(v)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    wrote = 0
    for mid, rows in by_match.items():
        if not mid:
            continue
        rows.sort(key=lambda x: int(x.get("seq") or 0))
        body = "KPL_LIVE_HIST = " + json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + ";\n"
        path = ARCHIVE_DIR / f"{mid}.js"
        if path.exists():
            try:
                if path.read_text(encoding="utf-8") == body:
                    continue
            except OSError:
                pass
        path.write_text(body, encoding="utf-8")
        wrote += 1
    # Existing shards are preserved; exporting never removes local archives.
    if wrote:
        print(f"  live_hist shards: {wrote} written / {len(by_match)} matches")


def _snapshot_camps(battle_id: str) -> tuple[str, str]:
    """本局阵营队名：取快照最后一帧的 camp1/camp2 队名（与 win_camp 同一套顺序）。"""
    snap_dir = RAW_DIR / battle_id
    if not snap_dir.is_dir():
        return "", ""
    try:
        files = sorted(snap_dir.glob("*.json"))
    except OSError:
        return "", ""
    for f in reversed(files):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        d = obj.get("data") or {}
        c1 = str((d.get("camp1") or {}).get("team_name") or "")
        c2 = str((d.get("camp2") or {}).get("team_name") or "")
        if c1 and c2:
            return c1, c2
    return "", ""


def repair_orientation(hist: dict) -> int:
    """把归档里"大场顺序"的旧条目纠正成"本局阵营顺序"。

    win / pts 一直是本局阵营口径（pts[1] = camp1 胜率），只有 t1/t2 可能是大场顺序；
    两者混用就会出现"KSG 3:0 却写成 杭州LGD.NBW 赢"这类反了的结果。
    这里按队名对齐，比分、图标跟着队名走；重复执行无副作用。
    """
    fixed = 0
    for bid, cur in hist.items():
        c1, c2 = str(cur.get("bt1") or ""), str(cur.get("bt2") or "")
        if not (c1 and c2):
            c1, c2 = _snapshot_camps(bid)
            if not (c1 and c2):
                continue
            cur["bt1"], cur["bt2"] = c1, c2
        old_t1, old_t2 = str(cur.get("t1") or ""), str(cur.get("t2") or "")
        if old_t1 == c1 and old_t2 == c2:
            continue
        icon = {old_t1: str(cur.get("i1") or ""), old_t2: str(cur.get("i2") or "")}
        swap_score = old_t1 != c1 and old_t2 == c1
        cur["t1"], cur["t2"] = c1, c2
        cur["i1"], cur["i2"] = icon.get(c1, cur.get("i1")), icon.get(c2, cur.get("i2"))
        if swap_score:
            cur["score1"], cur["score2"] = cur.get("score2"), cur.get("score1")
        fixed += 1
        print(f"  repaired orientation: {bid} {old_t1} vs {old_t2} -> {c1} vs {c2}")
    return fixed


def extract_series(battle_id: str, min_pts: int = 3) -> dict | None:
    """从快照重放：模型胜率 + 全部指标序列 + 选手经济/伤害 + 预测-实际对照。

    归档要求 >=3 点（曲线可复盘）；直播局放宽到 >=1 点，开赛第 2 分钟就能上实时页。
    """
    try:
        tl = _replay_v11_timeline(battle_id)
    except Exception:
        return None
    if tl is None or len(tl) == 0:
        return None
    battle_dir, _ = _resolve_battle_snapshot_dir(battle_id)
    if battle_dir is None:
        return None
    snaps = load_battle_jsons(battle_dir)
    if not snaps:
        return None
    by_bin = {}
    for s in snaps:
        by_bin[max(int(s.get("minute_bin") or 1), 1)] = s  # 同分钟取最后一帧

    # 选手名单（最后一帧，camp1 五人 + camp2 五人）
    last = snaps[-1]
    names, pcamp = [], []
    players = sorted(last.get("players") or [],
                     key=lambda p: (int(p.get("camp") or 0), str(p.get("position") or "")))
    for p in players:
        nm = str(p.get("player_name") or p.get("actual_player_name") or "").strip()
        names.append(nm)
        pcamp.append(int(p.get("camp") or 0))
    if len(names) != 10:
        names, pcamp = [], []

    pts = []
    for _, r in tl.iterrows():
        bin_id = int(r.get("minute_bin") or 0)
        s = by_bin.get(bin_id)
        if not s:
            continue
        row = [
            round(float(s.get("minute") or bin_id), 1),
            round(float(r.get("camp1_win_prob") or 0.5), 3),
            int(s.get("camp1_gold") or 0), int(s.get("camp2_gold") or 0),
            int(s.get("camp1_kill") or 0), int(s.get("camp2_kill") or 0),
            int(s.get("camp1_tower") or 0), int(s.get("camp2_tower") or 0),
            int(s.get("camp1_lord") or 0), int(s.get("camp2_lord") or 0),
            int(s.get("camp1_dark_tyrant") or 0), int(s.get("camp2_dark_tyrant") or 0),
        ]
        ps = sorted(s.get("players") or [],
                    key=lambda p: (int(p.get("camp") or 0), str(p.get("position") or "")))
        for p in ps[:10]:
            try:
                row.append(int(float(p.get("gold") or 0)))
                row.append(int(float(p.get("hurt_to_hero_total") or 0)))
            except (TypeError, ValueError):
                row.append(0)
                row.append(0)
        while len(row) < 12 + 20:
            row.append(0)
        pts.append(row)
    if len(pts) < max(1, int(min_pts)):
        return None
    if len(pts) > MAX_POINTS:
        step = max(1, len(pts) // MAX_POINTS)
        pts = pts[::step]

    # 预测-实际对照：t 时刻金差的"5 分钟前预测值"
    gpred = []
    for row in pts:
        m_now = row[0]
        prev = [(r2[0], r2[2] - r2[3]) for r2 in pts if m_now - 5 <= r2[0] <= m_now - 1.5]
        if len(prev) >= 3:
            n = len(prev)
            sx = sum(p[0] for p in prev); sy = sum(p[1] for p in prev)
            sxx = sum(p[0] * p[0] for p in prev); sxy = sum(p[0] * p[1] for p in prev)
            den = n * sxx - sx * sx
            if abs(den) > 1e-9:
                slope = (n * sxy - sx * sy) / den
                inter = (sy - slope * sx) / n
                gpred.append([m_now, int((slope * m_now + inter) * 0.85)])
    return {"pts": pts, "names": names, "pcamp": pcamp, "gpred": gpred,
            "bt1": str(last.get("camp1_team") or ""), "bt2": str(last.get("camp2_team") or "")}


_last_today = {"date": "", "rows": []}


def find_today_matches() -> list[dict]:
    global _last_today
    import datetime
    today = datetime.date.today().isoformat()
    out = []
    for lid in RECENT_LEAGUES:
        d = api_get(BASE_URL_LEAGUE, {"league_id": lid}, timeout=10)
        for m in (d or {}).get("results") or []:
            if not isinstance(m, dict) or not str(m.get("start_time") or "").startswith(today):
                continue
            c1, c2 = m.get("camp1") or {}, m.get("camp2") or {}
            out.append({
                "matchId": str(m.get("match_id") or ""), "leagueId": lid,
                "t1": str(c1.get("team_name") or ""), "t2": str(c2.get("team_name") or ""),
                "i1": str(c1.get("team_icon") or ""), "i2": str(c2.get("team_icon") or ""),
                "score1": int(c1.get("score") or 0), "score2": int(c2.get("score") or 0),
                "st": int(m.get("status") or 0),
                "stage": str(m.get("match_stage_name") or ""),
                "time": str(m.get("start_time") or "")[11:16],
                "bo": int(m.get("bo") or 0),
            })
    if out:
        _last_today = {"date": today, "rows": out}
    elif _last_today["date"] == today:
        return _last_today["rows"]  # 查询暂败（限流）时回退当日缓存，避免显示回退
    return out


def find_live_battles() -> list[dict]:
    out = []
    for lid in RECENT_LEAGUES:
        d = api_get(BASE_URL_LEAGUE, {"league_id": lid}, timeout=10)
        for m in (d or {}).get("results") or []:
            if int(m.get("status") or 0) != 1:
                continue
            mid = str(m.get("match_id") or "")
            d2 = api_get(BASE_URL_MATCH, {"match_id": mid}, timeout=10)
            for b in (d2 or {}).get("results") or []:
                if int(b.get("status") or 0) == 1 and b.get("battle_id"):
                    c1, c2 = m.get("camp1") or {}, m.get("camp2") or {}
                    out.append({
                        "matchId": mid, "battleId": str(b["battle_id"]),
                        "seq": int(b.get("battle_seq") or 0),
                        "t1": str(c1.get("team_name") or ""), "i1": str(c1.get("team_icon") or ""),
                        "t2": str(c2.get("team_name") or ""), "i2": str(c2.get("team_icon") or ""),
                        "score1": int(c1.get("score") or 0), "score2": int(c2.get("score") or 0),
                        "stage": str(m.get("match_stage_name") or ""), "league": lid,
                    })
    return out


def collect_recent_finished() -> list[dict]:
    import datetime
    days = {datetime.date.today().isoformat(),
            (datetime.date.today() - datetime.timedelta(days=1)).isoformat()}
    out = []
    for lid in RECENT_LEAGUES:
        d = api_get(BASE_URL_LEAGUE, {"league_id": lid}, timeout=10)
        for m in (d or {}).get("results") or []:
            if not isinstance(m, dict):
                continue
            st = str(m.get("start_time") or "")
            if st[:10] not in days:
                continue
            c1, c2 = m.get("camp1") or {}, m.get("camp2") or {}
            mid = str(m.get("match_id") or "")
            d2 = api_get(BASE_URL_MATCH, {"match_id": mid}, timeout=10)
            for b in (d2 or {}).get("results") or []:
                if int(b.get("status") or 0) != 2 or not b.get("battle_id"):
                    continue
                out.append({
                    "battleId": str(b["battle_id"]), "matchId": mid,
                    "seq": int(b.get("battle_seq") or 0), "win": int(b.get("win_camp") or 0),
                    "t1": str(c1.get("team_name") or ""), "i1": str(c1.get("team_icon") or ""),
                    "t2": str(c2.get("team_name") or ""), "i2": str(c2.get("team_icon") or ""),
                    "score1": int(c1.get("score") or 0), "score2": int(c2.get("score") or 0),
                    "date": st[:10],
                })
    return out


def build_once() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    global DISPLAY_CALIB
    # 校准表由 calibrate_replay.py 异步生成；每轮重读，但只接受当前模型 fingerprint 的表。
    DISPLAY_CALIB = load_calibrator(model_fp=_MODEL_FP)
    # ---- 预测归档（多指标结构；旧结构自动重录） ----
    hist = load_history()
    repair_orientation(hist)
    added = 0
    for f in collect_recent_finished():
        bid = f["battleId"]
        cur = hist.get(bid)
        if cur and cur.get("pts"):
            continue
        if added >= 2:
            break
        snap_dir = RAW_DIR / bid
        try:
            n_frames = len(list(snap_dir.glob("*.json"))) if snap_dir.is_dir() else 0
        except OSError:
            n_frames = 0
        if n_frames < 8:
            continue
        series = extract_series(bid)
        if not series:
            continue
        # 胜负字段（win_camp）是 battle 级阵营；队名/比分必须换成 battle 级并保持自洽
        orig_t1 = f.get("t1")
        if series.get("bt1"):
            f["t1"], f["t2"] = series["bt1"], series["bt2"]
            if orig_t1 and orig_t1 != series["bt1"]:
                f["score1"], f["score2"] = f.get("score2"), f.get("score1")
                f["i1"], f["i2"] = f.get("i2"), f.get("i1")
        f.update(series)
        f["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        hist[bid] = f
        added += 1
        print(f"  archived: G{f['seq']} {f['t1']} vs {f['t2']} ({len(f['pts'])} pts)")

    # ---- 进行中的局（实时序列） ----
    matches = []
    priors = load_priors()
    for lv in find_live_battles():
        series = extract_series(lv["battleId"], min_pts=1)
        if not series:
            continue
        # 与归档一致：队名/比分/图标全部对齐 battle 级阵营（胜率与金差都是 battle 视角）
        orig_t1 = lv.get("t1")
        if series.get("bt1"):
            lv["t1"], lv["t2"] = series["bt1"], series["bt2"]
            if orig_t1 and orig_t1 != series["bt1"]:
                lv["score1"], lv["score2"] = lv.get("score2"), lv.get("score1")
                lv["i1"], lv["i2"] = lv.get("i2"), lv.get("i1")
        pts = series["pts"]
        m_now = pts[-1]
        # 展示层：分阶段后校准 → 赛前先验按时间/金差融合 → 2–3 分钟 EMA + 每分钟限速。
        prior_camp1 = prior_for_match(priors, lv.get("matchId", ""), series.get("bt1") or lv.get("t1", ""))
        calibrated = []
        for r in pts:
            p = calibrate_probability(r[1], r[0], DISPLAY_CALIB)
            p, _w = blend_prior(p, r[0], prior_camp1, r[2] - r[3])
            calibrated.append((r[0], p))
        smooth_pts = ema_smooth(calibrated)
        m_smooth = smooth_pts[-1][1] if smooth_pts else calibrated[-1][1]
        obj_win, obj_label = objective_window(m_now[0])
        display = build_display(m_now[0], calibrated[-1][1], m_smooth, obj_win, obj_label, len(pts))
        display["prematch_prior"] = None if prior_camp1 is None else round(prior_camp1, 4)
        display["prior_weight"] = round(prior_weight(m_now[0], m_now[2] - m_now[3]), 3)
        win_pts = [(r[0], r[1] * 100) for r in smooth_pts[-12:]]
        gd_pts = [(r[0], r[2] - r[3]) for r in pts[-12:]]

        def lin(pp, ahead):
            if len(pp) < 4:
                return None
            n = len(pp)
            sx = sum(p[0] for p in pp); sy = sum(p[1] for p in pp)
            sxx = sum(p[0] * p[0] for p in pp); sxy = sum(p[0] * p[1] for p in pp)
            den = n * sxx - sx * sx
            if abs(den) < 1e-9:
                return None
            slope = (n * sxy - sx * sy) / den
            inter = (sy - slope * sx) / n
            return slope * (pp[-1][0] + ahead) + inter

        def damp(x):
            return None if x is None else max(5.0, min(95.0, 50 + (x - 50) * 0.7))

        p3, p5 = damp(lin(win_pts, 3)), damp(lin(win_pts, 5))
        g3, g5 = lin(gd_pts, 3), lin(gd_pts, 5)
        gold_spd = 0.0
        if len(gd_pts) >= 2 and gd_pts[-1][0] > gd_pts[0][0]:
            gold_spd = (gd_pts[-1][1] - gd_pts[0][1]) / (gd_pts[-1][0] - gd_pts[0][0])
        dirn = "flat"
        if p3 is not None:
            if p3 - m_smooth * 100 > 2:
                dirn = "up"
            elif p3 - m_smooth * 100 < -2:
                dirn = "down"
        matches.append({
            **{k: lv[k] for k in ("matchId", "battleId", "seq", "t1", "i1", "t2", "i2", "score1", "score2", "league")},
            "minute": round(m_now[0], 1),
            "prob": m_now[1],
            "probSmooth": round(m_smooth, 4),
            "ptsSmooth": [[round(m, 1), round(p, 4)] for m, p in smooth_pts],
            "display": display,
            "gd": m_now[2] - m_now[3],
            "goldSpd": round(gold_spd),
            "names": series["names"], "pcamp": series["pcamp"],
            "pts": pts, "gpred": series["gpred"],
            "forecast": {
                "p3": round(p3 / 100, 3) if p3 is not None else None,
                "p5": round(p5 / 100, 3) if p5 is not None else None,
                "g3": round(g3) if g3 is not None else None,
                "g5": round(g5) if g5 is not None else None,
                "dir": dirn,
            },
        })
        print(f"  live: {lv['t1']} {lv['score1']}:{lv['score2']} {lv['t2']} | G{lv['seq']} "
              f"{m_now[0]:.0f}′ | prob={m_now[1]:.2f}→{m_smooth:.2f} ({display['state']}) "
              f"gd={m_now[2]-m_now[3]:+d} | 5min→{p5 and round(p5)}%")

    # ---- 归档：全量留在主项目，网站按场分片 ----
    hist_list = sorted(hist.values(), key=lambda x: x.get("updated", ""), reverse=True)
    for old in hist_list[HISTORY_KEEP:]:
        hist.pop(old.get("battleId"), None)
    save_history(hist)

    # 每场比赛一个分片（match.html 按 matchId 按需加载），只写内容有变化的
    write_archive_shards(hist)

    hist_list = sorted(hist.values(), key=lambda x: x.get("updated", ""), reverse=True)[:LIVE_RECENT]

    payload = {
        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "today": find_today_matches(),
        "matches": matches,
        "history": hist_list,
    }
    core_new = json.dumps({k: v for k, v in payload.items() if k != "updatedAt"},
                          ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    core_old = ""
    try:
        if OUT.exists():
            txt = OUT.read_text(encoding="utf-8")
            old_obj = json.loads(txt[txt.index("=") + 1:].rstrip().rstrip(";"))
            core_old = json.dumps({k: v for k, v in old_obj.items() if k != "updatedAt"},
                                  ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except Exception:
        pass
    if core_new != core_old:
        tmp = OUT.with_suffix(".js.tmp")
        tmp.write_text("KPL_LIVE = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
                       encoding="utf-8")
        tmp.replace(OUT)
    print(f"  live.js {'updated' if core_new != core_old else 'unchanged'} ({len(matches)} live, {len(hist_list)} archived)")
    return len(matches)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=0)
    args = ap.parse_args()
    if args.watch <= 0:
        build_once()
        return
    print(f"live loop: every {args.watch}s, Ctrl+C to stop")
    while True:
        try:
            print(f"[{time.strftime('%H:%M:%S')}]")
            build_once()
        except KeyboardInterrupt:
            print("stop.")
            break
        except Exception as exc:
            print(f"  !! {exc}")
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
