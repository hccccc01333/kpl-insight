# -*- coding: utf-8 -*-
"""重放 vs 直播：固定回归测试。

问题：站点上的胜率有两条来源——
  ① 直播期写下的预测 CSV（monitor 边采边算，当时是哪个模型就是哪个模型）
  ② 事后重放（拿当前模型把同一局的快照再算一遍）
两者不是一回事：模型换过、特征补过、护栏改过。如果重放和直播系统性偏离，
那么"用重放算出来的任何指标"都不能和"直播档案的指标"互相印证。

这个脚本做三件事：
  1. 对同一批局，分别取 live（CSV）与 replay（当前模型逐帧重算），按分钟对齐；
  2. 报偏差分布：|Δp| 的均值/中位/p90/max、方向一致率、两条曲线的 Brier 差；
  3. 存一份 baseline，之后的运行只和 baseline 比漂移——这才叫"回归测试"：
     不预设"偏差应该小于多少"（没有理论值），只保证"不会悄悄变"。

用法：
    python -m kpl_insight.models.replay_check --baseline     # 首次：写 baseline
    python -m kpl_insight.models.replay_check                # 之后：比漂移，漂了就 exit 1
    python -m kpl_insight.models.replay_check --jobs 6       # 并行度
    python -m kpl_insight.models.replay_check --refresh      # 忽略缓存重算

缓存：data/realtime/replay_cache/<battle>.json，按模型指纹失效。
      首次跑满 185 局约 40 分钟（单进程），并行后 6–8 分钟；之后读缓存秒出。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from kpl_insight.paths import PROJECT_ROOT
REALTIME = PROJECT_ROOT / "data" / "realtime"
PRED_DIR = REALTIME / "predictions"
CACHE_DIR = REALTIME / "replay_cache"
REPORT_PATH = REALTIME / "replay_vs_live_report.json"
BASELINE_PATH = REALTIME / "replay_vs_live_baseline.json"

CHECKPOINTS = (8, 12, 16)
MIN_BATTLES = 20   # 少于这个数不写 baseline：空样本会变成"永远 PASS"的假门禁

# 漂移容忍度：超过就判定"重放链路变了"，需要人看一眼再更新 baseline。
# 这些数字不是"正确性阈值"，是"变化检测阈值"——故意设得比噪声宽一点。
TOL = {
    "median_abs_delta": 0.02,     # 中位 |Δp| 上升超过 0.02
    "direction_agree": 0.03,      # 方向一致率下降超过 0.03
    "brier_gap": 0.03,            # (replay Brier − live Brier) 变化超过 0.03
}


def model_fingerprint(artifact: dict) -> str:
    return f"{artifact.get('version')}|{artifact.get('trained_at')}|{len(artifact.get('feature_columns') or [])}"


def read_live(battle_id: str) -> dict[int, float]:
    """直播 CSV → {minute_bin: 该分钟最后一帧的 camp1 胜率}。不插值、不外推。"""
    path = PRED_DIR / f"{battle_id}.csv"
    if not path.exists():
        return {}
    out: dict[int, float] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    p = float(row.get("camp1_win_prob") or "")
                    m = float(row.get("minute") or "")
                except (TypeError, ValueError):
                    continue
                if p != p:
                    continue
                out[max(int(m), 1)] = round(p, 6)
    except OSError:
        return {}
    return out


def _ensure_legacy_loss_alias() -> None:
    """sklearn>=1.9 把 _loss 搬进 sklearn._loss，老 artifact 仍按顶层模块名反序列化。"""
    try:
        from sklearn._loss import _loss as sklearn_loss
    except Exception:
        return
    sys.modules.setdefault("_loss", sklearn_loss)


def _init_worker(artifact_path: str):
    """每个 worker 只加载一次模型 + 快照索引。

    注意：list_labeled_real_battles() 会扫 185 个快照目录，放到 _work 里会变成
    "每局扫一遍"，并行也救不回来（首版就是这么超时的）。
    """
    global _ART, _BATTLES
    import joblib

    _ensure_legacy_loss_alias()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from kpl_insight.models.evaluate import list_labeled_real_battles

    _ART = joblib.load(artifact_path)
    _BATTLES = {b["battle_id"]: b for b in list_labeled_real_battles()}


def _work(args: tuple[str, str]) -> dict:
    """单局：读 live、跑 replay、对齐。放进程池里跑。"""
    battle_id, _label = args
    from kpl_insight.models.evaluate import timeline_predictions

    battle = _BATTLES.get(battle_id)
    if battle is None:
        return {"battle_id": battle_id, "error": "snapshot missing"}
    tl = timeline_predictions(_ART, battle)
    replay = {int(r.minute_bin): round(float(r.prob), 6) for r in tl.itertuples()}
    live = read_live(battle_id)
    common = sorted(set(live) & set(replay))
    return {
        "battle_id": battle_id,
        "label": int(battle["win_camp"] == 1),
        "win_camp": int(battle["win_camp"]),
        "live_n": len(live),
        "replay_n": len(replay),
        "aligned_n": len(common),
        "pairs": [[m, live[m], replay[m]] for m in common],
    }


def pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[i]


def aggregate(rows: list[dict]) -> dict:
    deltas: list[float] = []
    agree = total = 0
    brier_live = brier_replay = 0.0
    brier_n = 0
    per_battle = []
    cp = {m: {"n": 0, "dsum": 0.0, "live_hit": 0, "replay_hit": 0} for m in CHECKPOINTS}

    for r in rows:
        if r.get("error") or not r["pairs"]:
            continue
        bd, bl, br, bn = [], 0.0, 0.0, 0
        for m, p_live, p_rep in r["pairs"]:
            d = abs(p_live - p_rep)
            bd.append(d)
            deltas.append(d)
            total += 1
            if (p_live >= 0.5) == (p_rep >= 0.5):
                agree += 1
            if r["label"] is not None:
                y = 1.0 if r["label"] else 0.0
                bl += (p_live - y) ** 2
                br += (p_rep - y) ** 2
                bn += 1
            if m in cp:
                cp[m]["n"] += 1
                cp[m]["dsum"] += d
                if r["label"] is not None:
                    y = 1.0 if r["label"] else 0.0
                    cp[m]["live_hit"] += int((p_live >= 0.5) == (y > 0.5))
                    cp[m]["replay_hit"] += int((p_rep >= 0.5) == (y > 0.5))
        if bn:
            brier_live += bl
            brier_replay += br
            brier_n += bn
        per_battle.append(
            {
                "battle_id": r["battle_id"],
                "aligned_n": len(bd),
                "median_delta": round(pct(bd, 0.5), 4),
                "max_delta": round(max(bd), 4),
            }
        )

    per_battle.sort(key=lambda x: -x["median_delta"])
    return {
        "battles": len(per_battle),
        "aligned_frames": total,
        "median_abs_delta": round(pct(deltas, 0.5), 4),
        "p90_abs_delta": round(pct(deltas, 0.9), 4),
        "max_abs_delta": round(max(deltas), 4) if deltas else 0.0,
        "direction_agree": round(agree / total, 4) if total else 0.0,
        "brier_live": round(brier_live / brier_n, 4) if brier_n else None,
        "brier_replay": round(brier_replay / brier_n, 4) if brier_n else None,
        "brier_gap": round((brier_replay - brier_live) / brier_n, 4) if brier_n else None,
        "brier_frames": brier_n,
        "checkpoints": {
            str(m): {
                "n": v["n"],
                "mean_abs_delta": round(v["dsum"] / v["n"], 4) if v["n"] else None,
                "live_hit": round(v["live_hit"] / v["n"], 4) if v["n"] else None,
                "replay_hit": round(v["replay_hit"] / v["n"], 4) if v["n"] else None,
            }
            for m, v in cp.items()
        },
        "worst_battles": per_battle[:5],
    }


def by_split(rows: list[dict], test_ids: set[str], calib_ids: set[str]) -> dict:
    """按训练 / 校准 / 考试段拆开看差距。

    必须拆：replay 用的是当前模型，如果这段数据在它的训练集里，replay 的优势就掺了"背答案"。
    只有 test 段（模型没见过）的差距才是"重放 vs 直播"的干净估计。
    """
    out = {}
    for name, pred in (
        ("test", lambda b: b in test_ids),
        ("calib", lambda b: b in calib_ids),
        ("train", lambda b: b not in test_ids and b not in calib_ids),
    ):
        n = 0
        bl = br = 0.0
        for r in rows:
            if r.get("error") or not r["pairs"] or r.get("label") is None:
                continue
            if not pred(r["battle_id"]):
                continue
            y = 1.0 if r["label"] else 0.0
            for _m, p_live, p_rep in r["pairs"]:
                n += 1
                bl += (p_live - y) ** 2
                br += (p_rep - y) ** 2
        out[name] = {
            "frames": n,
            "brier_live": round(bl / n, 4) if n else None,
            "brier_replay": round(br / n, 4) if n else None,
            "gap": round((br - bl) / n, 4) if n else None,
        }
    return out


def main() -> None:
    import joblib

    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true", help="写 baseline（覆盖）")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 局（调试用）")
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    art_path = PROJECT_ROOT / "output" / "models" / "v9_official_platform.joblib"
    _ensure_legacy_loss_alias()
    art = joblib.load(art_path)
    fp = model_fingerprint(art)
    print(f"model: {art.get('version')} · trained_at={art.get('trained_at')} · fp={fp}")

    # 候选：既有直播 CSV、又有快照的局。只按 CSV 名字取前 N 会撞到没有快照的局
    # （212 个 CSV 里只有 185 局有 clean 快照），所以先在父进程里过滤。
    from kpl_insight.models.evaluate import list_labeled_real_battles

    battles = list_labeled_real_battles()
    known = {b["battle_id"] for b in battles}
    live_ids = sorted(p.stem for p in PRED_DIR.glob("*.csv"))
    no_snap = [b for b in live_ids if b not in known]
    candidates = [b for b in live_ids if b in known]
    if args.limit:
        candidates = candidates[: args.limit]
    print(f"直播档案 {len(live_ids)} 局 · 其中有快照 {len(candidates)} 局 · 无快照跳过 {len(no_snap)} 局")

    t0 = time.time()
    rows: list[dict] = []
    todo: list[tuple[str, bool]] = []
    for bid in candidates:
        cache = CACHE_DIR / f"{bid}.json"
        if cache.exists() and not args.refresh:
            try:
                obj = json.loads(cache.read_text(encoding="utf-8"))
                if obj.get("fp") == fp:
                    rows.append(obj["row"])
                    continue
            except (OSError, json.JSONDecodeError):
                pass
        todo.append((bid, True))
    print(f"缓存命中 {len(rows)} · 需重算 {len(todo)}")

    if todo:
        with ProcessPoolExecutor(max_workers=args.jobs, initializer=_init_worker, initargs=(str(art_path),)) as ex:
            for i, res in enumerate(ex.map(_work, todo), 1):
                if i % 10 == 0 or i == len(todo):
                    print(f"  {i}/{len(todo)} · {time.time() - t0:.0f}s", flush=True)
                if res.get("error"):
                    print(f"  skip {res['battle_id']}: {res['error']}")
                    continue
                (CACHE_DIR / f"{res['battle_id']}.json").write_text(
                    json.dumps({"fp": fp, "row": res}, ensure_ascii=False), encoding="utf-8"
                )
                rows.append(res)

    agg = aggregate(rows)
    if agg["battles"] < MIN_BATTLES:
        print(f"\n[FAIL] 有效局数只有 {agg['battles']}（< {MIN_BATTLES}），不写 baseline / report。")
        print("       常见原因：快照目录缺失，或模型指纹变了但缓存没重建。先看上面的 skip 行。")
        sys.exit(1)
    report = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": {"version": art.get("version"), "trained_at": art.get("trained_at"), "fp": fp},
        "note": (
            "live = 直播期写入的预测 CSV（可能是旧模型）；replay = 当前模型对同一批快照逐帧重算。"
            "两者不是同一件事，本报告的用途是量化差异并锁住它，不是证明某一方正确。"
        ),
        "summary": agg,
        "by_split": by_split(
            rows,
            {str(x) for x in (art.get("holdout_battles") or [])},
            {str(x) for x in (art.get("calib_battles") or [])},
        ),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 重放 vs 直播（按分钟对齐） ===")
    print(f"  局数 {agg['battles']} · 对齐帧 {agg['aligned_frames']}")
    print(f"  |Δp| 中位 {agg['median_abs_delta']:.3f} · p90 {agg['p90_abs_delta']:.3f} · max {agg['max_abs_delta']:.3f}")
    print(f"  方向一致率 {agg['direction_agree']:.3f}")
    print(f"  Brier  live {agg['brier_live']} · replay {agg['brier_replay']} · 差 {agg['brier_gap']}")
    for m, v in agg["checkpoints"].items():
        print(
            f"  {m:>2}′ n={v['n']:4d} 平均|Δp|={v['mean_abs_delta']} "
            f"live命中={v['live_hit']} replay命中={v['replay_hit']}"
        )
    print("  偏差最大的局：")
    for w in agg["worst_battles"]:
        print(f"    {w['battle_id']}  中位 {w['median_delta']}  最大 {w['max_delta']}  帧 {w['aligned_n']}")

    print("\n  按训练/校准/考试段拆（只有 test 段是干净估计）：")
    for name, v in report["by_split"].items():
        if v["frames"]:
            print(
                f"    {name:6s} 帧 {v['frames']:5d}  live {v['brier_live']:.4f}  "
                f"replay {v['brier_replay']:.4f}  差 {v['gap']:+.4f}"
            )

    if args.baseline or not BASELINE_PATH.exists():
        BASELINE_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写 baseline → {BASELINE_PATH.name}（首次运行会自动建立）")
        return

    base = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    base_sum = base["summary"]
    drift = {
        "median_abs_delta": agg["median_abs_delta"] - base_sum["median_abs_delta"],
        "direction_agree": agg["direction_agree"] - base_sum["direction_agree"],
        "brier_gap": (agg["brier_gap"] or 0) - (base_sum["brier_gap"] or 0),
    }
    fails = []
    if drift["median_abs_delta"] > TOL["median_abs_delta"]:
        fails.append(f"中位|Δp| 上升 {drift['median_abs_delta']:+.3f} > {TOL['median_abs_delta']}")
    if drift["direction_agree"] < -TOL["direction_agree"]:
        fails.append(f"方向一致率下降 {drift['direction_agree']:+.3f} < -{TOL['direction_agree']}")
    if abs(drift["brier_gap"]) > TOL["brier_gap"]:
        fails.append(f"Brier 差变化 {drift['brier_gap']:+.3f} 超过 ±{TOL['brier_gap']}")

    print(f"\n=== 与 baseline 对比（baseline 生成于 {base.get('generatedAt')}） ===")
    for k, v in drift.items():
        print(f"  {k:20s} {v:+.4f}")
    if fails:
        print("\n[FAIL] 重放链路发生漂移，需要人工确认：")
        for f in fails:
            print("  - " + f)
        sys.exit(1)
    print("\n[PASS] 未超出容忍度")


if __name__ == "__main__":
    main()
