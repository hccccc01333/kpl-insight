"""
KPL 官方赛程自动监控与实时采集脚本

能力：
- 自动从官方赛程接口识别进行中或最近一场比赛；
- 自动发现当前 battle_id；
- 多副本探测获取最新局内数据；
- 爬虫与模型并行：采集线程高频写 raw/frames，推理线程异步写 predictions；
- 保存 raw snapshots、frames CSV、实时预测 CSV、monitor_status.json；
- 一场 BO 全部结束后，等待下一场开赛时间并自动切换预测；
- 当日全部比赛结束后统一重训一次模型，并热加载新模型（非每场/每局都训练）。

运行示例：
    python -m kpl_insight.collection.monitor --interval 0.1
    python -m kpl_insight.collection.monitor --no-auto-train
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from kpl_insight.core import (
    LEAGUE_ID,
    REWIND_ACCEPT_TOLERANCE_SEC,
    PREDICTION_CSV_FIELDS,
    PREDICTION_DIR,
    RAW_DIR,
    REALTIME_DIR,
    ScheduleCenter,
    ScheduleMatch,
    adaptive_poll_interval,
    compute_lag_sec,
    fetch_freshest_battle,
    is_monotonic_snapshot,
    load_model,
    parse_snapshot,
    predict_probability,
    refresh_schedule_archive,
    sanitize_lag_sec,
)
from kpl_insight.models.train import train_v9_model


STATUS_FILE = REALTIME_DIR / "monitor_status.json"
TRAIN_STATUS_FILE = REALTIME_DIR / "train_status.json"
FRAME_DIR = REALTIME_DIR / "frames"
FRAME_CSV_FIELDS = [
    "collected_at",
    "match_id",
    "battle_id",
    "minute",
    "snapshot_time_sec",
    "lag_sec",
    "camp1_team",
    "camp2_team",
    "gold_diff",
    "kill_diff",
    "tower_diff",
    "status",
    "win_camp",
]
_SAVE_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="kpl-save")
_TRAIN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kpl-train")
_SENTINEL = object()


@dataclass
class CollectedFrame:
    match_id: str
    battle_id: str
    match_name: str
    collected_at: str
    raw: dict[str, Any]
    snap: dict[str, Any]
    lag_sec: float | None
    clock_jump: bool


@dataclass
class PipelineContext:
    artifact: dict
    collect_only: bool = False
    auto_train: bool = True
    train_after_matches: int = 0
    trained_session: bool = False
    training: bool = False
    last_data_sig: tuple[int, float] | None = None
    battle_anchors: dict[str, tuple[datetime, int]] = field(default_factory=dict)
    last_velocity_by_battle: dict[str, float] = field(default_factory=dict)
    last_snapshot_sec: dict[str, int] = field(default_factory=dict)
    last_frame_key: dict[str, tuple] = field(default_factory=dict)
    last_lag_sec: dict[str, float] = field(default_factory=dict)
    # Match API sometimes drops active battle_id mid-game; keep polling last known id.
    sticky_battle_by_match: dict[str, str] = field(default_factory=dict)
    frame_queue: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=800))
    # Deduped timeline: battle_id -> snapshot_time_sec -> latest unique frame.
    deduped_timeline: dict[str, dict[int, CollectedFrame]] = field(default_factory=dict)
    predicted_secs: dict[str, set[int]] = field(default_factory=dict)
    predict_history: dict[str, list[dict]] = field(default_factory=dict)
    collect_history: dict[str, list[dict]] = field(default_factory=dict)
    stop_event: threading.Event = field(default_factory=threading.Event)
    collect_interval_sec: float = 0.1
    last_battle_resolve_at: float = 0.0
    _status_lock: threading.Lock = field(default_factory=threading.Lock)
    _timeline_lock: threading.Lock = field(default_factory=threading.Lock)


def write_status(payload: dict, ctx: PipelineContext | None = None):
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **payload}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if ctx is not None:
        with ctx._status_lock:
            STATUS_FILE.write_text(text, encoding="utf-8")
    else:
        STATUS_FILE.write_text(text, encoding="utf-8")


def save_raw_snapshot(battle_id: str, payload: dict) -> Path:
    out_dir = RAW_DIR / battle_id
    out_dir.mkdir(parents=True, exist_ok=True)
    # Microseconds: 0.1s crawl would collide on second-only names.
    path = out_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_raw_snapshot_async(battle_id: str, payload: dict) -> None:
    _SAVE_EXECUTOR.submit(save_raw_snapshot, battle_id, payload)


def _append_csv(path: Path, fields: list[str], row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    use_fields = list(fields)
    if exists:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f), None)
        if header:
            use_fields = header
    full_row = {col: row.get(col, "") for col in use_fields}
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=use_fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(full_row)


def append_prediction(battle_id: str, row: dict):
    _append_csv(PREDICTION_DIR / f"{battle_id}.csv", list(PREDICTION_CSV_FIELDS), row)


def append_frame(battle_id: str, row: dict):
    """Crawl-only timeline (no model)."""
    _append_csv(FRAME_DIR / f"{battle_id}.csv", FRAME_CSV_FIELDS, row)


def frame_dedupe_key(snap: dict[str, Any]) -> tuple:
    """Identity of a crawl row: same game clock + board state => duplicate."""
    sec = int(snap.get("time_sec", 0) or snap.get("snapshot_time_sec", 0) or 0)
    return (
        sec,
        int(snap.get("camp1_gold", 0) or 0),
        int(snap.get("camp2_gold", 0) or 0),
        int(snap.get("camp1_kill", 0) or 0),
        int(snap.get("camp2_kill", 0) or 0),
        int(snap.get("camp1_tower", 0) or 0),
        int(snap.get("camp2_tower", 0) or 0),
        int(snap.get("status", 0) or 0),
        int(snap.get("win_camp", 0) or 0),
    )


def next_poll_interval(ctx: PipelineContext, battle_id: str | None, args) -> float:
    if not getattr(args, "adaptive", False) or not battle_id:
        return float(args.interval)
    velocity = ctx.last_velocity_by_battle.get(battle_id, 0.0)
    return float(
        adaptive_poll_interval(
            velocity,
            interval_calm=float(args.interval),
            interval_hot=float(args.interval_hot),
            hot_velocity_threshold=args.hot_velocity,
        )
    )


def ensure_battle_anchor(ctx: PipelineContext, battle_id: str, snap: dict) -> None:
    if battle_id in ctx.battle_anchors:
        return
    game_sec = int(snap.get("time_sec", 0) or snap.get("snapshot_time_sec", 0) or 0)
    if game_sec > 0:
        ctx.battle_anchors[battle_id] = (datetime.now(), game_sec)


def realtime_data_signature() -> tuple[int, float]:
    """Cheap signature: battle-dir count + newest mtime (no full JSON glob)."""
    if not RAW_DIR.exists():
        return 0, 0.0
    dirs = [p for p in RAW_DIR.iterdir() if p.is_dir()]
    if not dirs:
        return 0, 0.0
    latest = 0.0
    for d in dirs:
        try:
            mt = d.stat().st_mtime
            if mt > latest:
                latest = mt
            for child in d.iterdir():
                if child.suffix == ".json":
                    try:
                        cmt = child.stat().st_mtime
                        if cmt > latest:
                            latest = cmt
                            break  # one file peek is enough for "data changed" signal
                    except OSError:
                        continue
        except OSError:
            continue
    return len(dirs), latest


def write_train_status(payload: dict):
    TRAIN_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **payload}
    TRAIN_STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def recover_stale_train_status():
    """监控进程重启会杀死后台训练线程；启动时把残留的 training 落成 error。

    2026-10-20 20:45 触发重训，20:58 监控被重启，训练线程随之被杀，但状态文件
    一直停在 training。这里在启动时显式收尾，下一比赛日会重新触发。
    """
    try:
        cur = json.loads(TRAIN_STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    if str(cur.get("state")) != "training":
        return
    write_train_status(
        {
            "state": "error",
            "reason": str(cur.get("reason") or "interrupted"),
            "finished_matches": cur.get("finished_matches"),
            "needed_matches": cur.get("needed_matches"),
            "snapshot_dirs": cur.get("snapshot_dirs"),
            "message": "上次重训未完成（监控进程已重启），将在下一比赛日后重试",
        }
    )
    print("[TRAIN] 检测到上次重训被中断，状态已重置为 error；下一比赛日后会重试")


def today_match_progress(schedule: ScheduleCenter, date: str | None = None) -> tuple[int, int, list[ScheduleMatch]]:
    """Return finished_count, total_count, today's matches."""
    if date:
        today = [
            m for m in schedule.fetch_matches()
            if m.start_time and m.start_time.strftime("%Y-%m-%d") == date
        ]
    else:
        today = schedule.today_matches()
    finished = [m for m in today if m.status == 2]
    return len(finished), len(today), today


def matches_needed_for_train(schedule: ScheduleCenter, date: str | None, train_after_matches: int) -> int:
    _, total, _ = today_match_progress(schedule, date)
    if train_after_matches > 0:
        return min(train_after_matches, total) if total else train_after_matches
    return total if total else 3


def _train_job(ctx: PipelineContext, reason: str, finished_count: int, needed: int, sig: tuple[int, float]) -> None:
    try:
        artifact = train_v9_model(verbose=False)
        ctx.artifact = artifact
        ctx.last_data_sig = sig
        ctx.trained_session = True
        metrics = (
            artifact.get("metrics", {}).get("VotingMidlate")
            or artifact.get("metrics", {}).get("VotingV9")
            or {}
        )
        holdout = artifact.get("holdout_real", {}).get("all", {})
        write_train_status(
            {
                "state": "ready",
                "reason": reason,
                "finished_matches": finished_count,
                "needed_matches": needed,
                "snapshot_dirs": sig[0],
                "real_rows": artifact.get("real_rows", 0),
                "sim_rows": artifact.get("sim_rows", 0),
                "model_name": artifact.get("model_name", "Unknown"),
                "version": artifact.get("version", "V9"),
                "trained_at": artifact.get("trained_at", ""),
                "auc": metrics.get("auc"),
                "accuracy": metrics.get("accuracy"),
                "holdout_real_brier": holdout.get("brier"),
                "holdout_real_ece": holdout.get("ece"),
                "holdout_early_brier": artifact.get("holdout_real", {}).get("early", {}).get("brier"),
                "holdout_mid_brier": artifact.get("holdout_real", {}).get("mid", {}).get("brier"),
                "holdout_late_brier": artifact.get("holdout_real", {}).get("late", {}).get("brier"),
                "comeback_acc": artifact.get("holdout_comeback", {}).get("all", {}).get("accuracy"),
                "use_time_shrinkage": artifact.get("use_time_shrinkage"),
                "calibrator": "phase_isotonic" if artifact.get("calibrator_early") is not None else (
                    "isotonic" if artifact.get("calibrator") is not None else "none"
                ),
            }
        )
        write_status(
            {
                "state": "day_complete",
                "message": (
                    f"重训完成 holdout_brier={holdout.get('brier', float('nan')):.4f} "
                    f"(mixed AUC={metrics.get('auc', 0):.3f} 仅供参考)"
                ),
                "model_name": artifact.get("model_name", "Unknown"),
            }
        )
        print(
            f"[TRAIN] 完成 holdout_brier={holdout.get('brier', float('nan')):.4f} "
            f"mixed_auc={metrics.get('auc', 0):.3f} "
            f"real={artifact.get('real_rows', 0)} sim={artifact.get('sim_rows', 0)}"
        )
    except Exception as exc:
        write_train_status({"state": "error", "reason": reason, "message": str(exc)})
        write_status({"state": "train_error", "message": f"重训失败: {exc}"})
        print(f"[TRAIN] 失败: {exc}")
    finally:
        ctx.training = False


def try_retrain_once(ctx: PipelineContext, schedule: ScheduleCenter, date: str | None, reason: str) -> bool:
    """当日比赛打满后异步重训一次；主循环不阻塞采集。"""
    if not ctx.auto_train or ctx.training or ctx.trained_session:
        return False

    finished_count, total_count, _ = today_match_progress(schedule, date)
    needed = matches_needed_for_train(schedule, date, ctx.train_after_matches)
    if finished_count < needed:
        print(f"[TRAIN] 今日已完成 {finished_count}/{needed} 场，暂不训练")
        return False

    sig = realtime_data_signature()
    if sig[0] == 0:
        return False

    ctx.training = True
    write_status({"state": "training", "message": f"今日 {finished_count} 场比赛已结束，后台重训中（采集不中断）"})
    write_train_status(
        {
            "state": "training",
            "reason": reason,
            "finished_matches": finished_count,
            "needed_matches": needed,
            "snapshot_dirs": sig[0],
        }
    )
    print(f"[TRAIN] 后台启动 · 今日 {finished_count}/{needed} 场已结束 · dirs={sig[0]}")
    _TRAIN_EXECUTOR.submit(_train_job, ctx, reason, finished_count, needed, sig)
    return True


def maybe_train_after_batch(
    ctx: PipelineContext,
    schedule: ScheduleCenter,
    date: str | None,
    reason: str,
) -> None:
    finished_count, total_count, _ = today_match_progress(schedule, date)
    needed = matches_needed_for_train(schedule, date, ctx.train_after_matches)
    if finished_count >= needed:
        try_retrain_once(ctx, schedule, date, reason)


def seconds_until(start_time: datetime) -> int:
    return max(0, int((start_time - datetime.now()).total_seconds()))


def _find_active_match(schedule: ScheduleCenter) -> ScheduleMatch | None:
    """当前真正在打的比赛（status=1）。用于纠正“等未来场次时错过今天比赛”。"""
    try:
        for m in schedule.fetch_matches():
            if m.status == 1:
                return m
    except Exception:
        return None
    return None


def wait_until_start(
    match: ScheduleMatch,
    poll_sec: int,
    ctx: PipelineContext,
    label: str = "waiting_start",
    schedule: ScheduleCenter | None = None,
):
    if not match.start_time:
        return None
    last_print = 0.0
    last_active_check = 0.0
    last_schedule_refresh = time.monotonic()
    while True:
        wait_sec = seconds_until(match.start_time)
        if wait_sec <= 0:
            return None
        # 空窗期也要刷新赛程归档：新场次可能在等待期间发布，站点 data.js 依赖它。
        if time.monotonic() - last_schedule_refresh >= 1800:
            last_schedule_refresh = time.monotonic()
            try:
                n = refresh_schedule_archive()
                print(f"[SCHED] 空窗期刷新赛程缓存 {n} 场")
            except Exception as exc:
                print(f"[WARN] 空窗期赛程刷新失败: {exc}")
        if schedule is not None and time.monotonic() - last_active_check >= 30:
            last_active_check = time.monotonic()
            active = _find_active_match(schedule)
            if active and active.match_id != match.match_id:
                print(f"[SWITCH] 检测到进行中的比赛 {active.display_name}，切换监控")
                return active
        write_status(
            {
                "state": label,
                "match_id": match.match_id,
                "match": match.display_name,
                "team1": match.team1,
                "team2": match.team2,
                "start_time": match.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "seconds_until_start": wait_sec,
                "model_name": ctx.artifact.get("model_name", "Unknown"),
                "message": f"等待开赛，距离开赛还有 {wait_sec // 60} 分 {wait_sec % 60} 秒",
            }
        )
        now_mono = time.monotonic()
        if wait_sec > 600 and now_mono - last_print >= 300:
            print(
                f"[WAIT] {match.team1} vs {match.team2} "
                f"开赛倒计时 {wait_sec // 60:02d}:{wait_sec % 60:02d}"
            )
            last_print = now_mono
        elif wait_sec <= 600 and now_mono - last_print >= 60:
            print(
                f"[WAIT] {match.team1} vs {match.team2} "
                f"开赛倒计时 {wait_sec // 60:02d}:{wait_sec % 60:02d}"
            )
            last_print = now_mono
        time.sleep(min(poll_sec, wait_sec, 60))


def clear_battle_runtime(ctx: PipelineContext, match_id: str, battle_id: str) -> None:
    """Drop crawl-side state; predict history is cleared after finishing PRED."""
    ctx.collect_history.pop(battle_id, None)
    ctx.last_snapshot_sec.pop(battle_id, None)
    ctx.last_frame_key.pop(battle_id, None)
    if ctx.sticky_battle_by_match.get(match_id) == battle_id:
        ctx.sticky_battle_by_match.pop(match_id, None)


def enqueue_frame(ctx: PipelineContext, frame: CollectedFrame) -> bool:
    """Register onto deduped timeline (by game second), then wake the predict worker."""
    if ctx.collect_only:
        write_status({
            "state": "collecting", "pipeline": "collect-only",
            "match_id": frame.match_id, "battle_id": frame.battle_id,
            "minute": frame.snap.get("minute"),
            "message": "仅采集真实快照，未加载模型、未生成胜率",
        }, ctx)
        return True
    snap_sec = int(frame.snap.get("time_sec", 0) or frame.snap.get("snapshot_time_sec", 0) or 0)
    with ctx._timeline_lock:
        by_sec = ctx.deduped_timeline.setdefault(frame.battle_id, {})
        by_sec[snap_sec] = frame
    try:
        ctx.frame_queue.put_nowait((frame.battle_id, snap_sec))
        return True
    except queue.Full:
        try:
            ctx.frame_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            ctx.frame_queue.put_nowait((frame.battle_id, snap_sec))
            return True
        except queue.Full:
            print(f"[WARN] frame queue full, drop {frame.battle_id}@{snap_sec}s")
            return False


def predict_worker(ctx: PipelineContext) -> None:
    """Model module: pull unique game-seconds from the deduped timeline and score."""
    if ctx.collect_only:
        return
    print("[PRED] 推理线程已启动（按去重局时提取 → 算胜率）")
    while not ctx.stop_event.is_set():
        try:
            item = ctx.frame_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        if item is _SENTINEL:
            break
        try:
            if isinstance(item, CollectedFrame):
                process_prediction_frame(ctx, item)
            elif isinstance(item, tuple) and len(item) == 2:
                battle_id, snap_sec = item
                process_prediction_by_sec(ctx, str(battle_id), int(snap_sec))
        except Exception as exc:
            print(f"[PRED-ERR] {exc}")
            import traceback

            traceback.print_exc()
        finally:
            ctx.frame_queue.task_done()
    print("[PRED] 推理线程已退出")


def process_prediction_by_sec(ctx: PipelineContext, battle_id: str, snap_sec: int) -> None:
    """Pull one unique game-second from the deduped timeline and score win probability."""
    predicted = ctx.predicted_secs.setdefault(battle_id, set())
    if snap_sec > 0 and snap_sec in predicted:
        return

    with ctx._timeline_lock:
        frame = (ctx.deduped_timeline.get(battle_id) or {}).get(snap_sec)
    if frame is None:
        return

    if snap_sec > 0:
        predicted.add(snap_sec)
    _emit_prediction(ctx, frame)


def process_prediction_frame(ctx: PipelineContext, frame: CollectedFrame) -> None:
    """Direct entry: ensure frame is on the deduped timeline, then score that second."""
    snap_sec = int(frame.snap.get("time_sec", 0) or frame.snap.get("snapshot_time_sec", 0) or 0)
    with ctx._timeline_lock:
        ctx.deduped_timeline.setdefault(frame.battle_id, {})[snap_sec] = frame
    process_prediction_by_sec(ctx, frame.battle_id, snap_sec)


def _feature_hash(feats: dict, artifact: dict) -> str:
    cols = artifact.get("feature_columns") or []
    vals = []
    for c in cols:
        try:
            vals.append(round(float(feats.get(c, 0.0) or 0.0), 4))
        except (TypeError, ValueError):
            vals.append(None)
    return hashlib.sha1(json.dumps(vals, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]


def _emit_prediction(ctx: PipelineContext, frame: CollectedFrame) -> None:
    battle_id = frame.battle_id
    snap = frame.snap
    history = ctx.predict_history.setdefault(battle_id, [])
    artifact = ctx.artifact
    snap_sec = int(snap.get("time_sec", 0) or snap.get("snapshot_time_sec", 0) or 0)

    _t0 = time.perf_counter()
    prob, feats, explain = predict_probability(artifact, snap, history)
    predict_latency_ms = (time.perf_counter() - _t0) * 1000.0
    history.append(snap)
    if len(history) > 40:
        history[:] = history[-40:]

    ctx.last_velocity_by_battle[battle_id] = float(feats.get("gold_diff_velocity", 0.0))

    gold_guard_applied = float(feats.get("_gold_guard_applied", 0) or 0) > 0.5
    row = {
        "collected_at": frame.collected_at,
        "match_id": frame.match_id,
        "battle_id": battle_id,
        "minute": round(float(snap.get("minute", 0)), 2),
        "snapshot_time_sec": snap_sec,
        "lag_sec": frame.lag_sec if frame.lag_sec is not None else "",
        "camp1_team": snap.get("camp1_team"),
        "camp2_team": snap.get("camp2_team"),
        "camp1_win_prob": round(prob, 5),
        "camp2_win_prob": round(1 - prob, 5),
        "gold_diff": snap.get("camp1_gold", 0) - snap.get("camp2_gold", 0),
        "kill_diff": snap.get("camp1_kill", 0) - snap.get("camp2_kill", 0),
        "tower_diff": snap.get("camp1_tower", 0) - snap.get("camp2_tower", 0),
        "objective_value_score": round(float(feats.get("objective_value_score", 0)), 4),
        "tempo_swing_score": round(float(feats.get("tempo_swing_score", 0)), 4),
        "top_factor": explain[0]["factor"] if explain else "",
        # FeatureBuilder.explain 只是"原始特征绝对值最大"，不是模型归因；显式标注，避免误读
        "top_factor_kind": "narrative_feature_magnitude",
        "top_factor_note": "描述性输入摘要，非模型归因（不是 SHAP/因果贡献）",
        "gold_guard_applied": int(gold_guard_applied),
        "model_version": artifact.get("version") or "",
        "model_trained_at": artifact.get("trained_at") or "",
        "model_fp": f"{artifact.get('version') or ''}|{artifact.get('trained_at') or ''}|{len(artifact.get('feature_columns') or [])}",
        "feature_hash": _feature_hash(feats, artifact),
        "predict_latency_ms": round(predict_latency_ms, 2),
        "prob_raw": round(float(feats.get("_prob_raw", prob)), 5),
        "prob_model": round(float(prob), 5),
        "status": snap.get("status"),
        "win_camp": snap.get("win_camp"),
    }
    append_prediction(battle_id, row)

    battle_state = "finished" if int(snap.get("status", 0) or 0) == 2 else "running"
    write_status(
        {
            "state": battle_state,
            "match_id": frame.match_id,
            "battle_id": battle_id,
            "match": frame.match_name,
            "camp1_team": snap.get("camp1_team"),
            "camp2_team": snap.get("camp2_team"),
            "minute": row["minute"],
            "snapshot_time_sec": row["snapshot_time_sec"],
            "lag_sec": row["lag_sec"],
            "clock_jump": frame.clock_jump,
            "low_confidence": bool(feats.get("_low_confidence", 0)),
            "confidence": feats.get("_confidence", "high"),
            "camp1_win_prob": row["camp1_win_prob"],
            "camp2_win_prob": row["camp2_win_prob"],
            "gold_diff": row["gold_diff"],
            "top_factor": row["top_factor"],
            "top_factor_kind": "narrative_feature_magnitude",
            "top_factor_note": "描述性输入摘要，非模型归因（不是 SHAP/因果贡献）",
            "gold_guard_applied": gold_guard_applied,
            "poll_interval_sec": ctx.collect_interval_sec,
            "queue_size": ctx.frame_queue.qsize(),
            "pipeline": "crawl||predict@deduped_sec",
            "prediction_path": str(PREDICTION_DIR / f"{battle_id}.csv"),
            "frame_path": str(FRAME_DIR / f"{battle_id}.csv"),
            "model_name": artifact.get("model_name", "Unknown"),
        },
        ctx,
    )
    lag_note = (
        f" lag={frame.lag_sec:+.0f}s"
        if isinstance(frame.lag_sec, (int, float))
        else (" lag=clock_jump" if frame.clock_jump else "")
    )
    print(
        f"[PRED] {battle_id} t={snap_sec}s ({row['minute']:.1f}min) "
        f"{row['camp1_team']} {row['camp1_win_prob']:.1%} vs {row['camp2_team']} {row['camp2_win_prob']:.1%}"
        f"{lag_note} · q={ctx.frame_queue.qsize()}"
    )
    if int(snap.get("status", 0) or 0) == 2:
        ctx.predict_history.pop(battle_id, None)
        ctx.battle_anchors.pop(battle_id, None)
        ctx.last_velocity_by_battle.pop(battle_id, None)
        ctx.last_lag_sec.pop(battle_id, None)
        ctx.predicted_secs.pop(battle_id, None)
        with ctx._timeline_lock:
            ctx.deduped_timeline.pop(battle_id, None)


def collect_once(
    args,
    match_id: str,
    match: ScheduleMatch | None,
    ctx: PipelineContext,
) -> tuple[str, float]:
    """Crawl module only: fetch + save + enqueue. Never runs the model."""
    schedule = ScheduleCenter(args.league_id)
    match = match or schedule.get_match_by_id(match_id)
    wait_sec = max(1.0, float(args.interval))
    crawl_sec = float(args.interval)

    if not match_id:
        write_status({"state": "waiting_schedule", "message": "未发现可监控赛程"}, ctx)
        print("[WAIT] 未发现可监控赛程")
        return "waiting_schedule", wait_sec

    if match and match.status == 2:
        print(f"[DONE] match={match_id} 已结束 · {match.display_name}")
        return "match_finished", wait_sec

    battle_id = args.battle_id
    used_sticky = False
    now_mono = time.monotonic()
    # Match API resolve at most ~1Hz; battle crawl stays at --interval.
    if not battle_id:
        sticky = ctx.sticky_battle_by_match.get(match_id)
        if sticky and (now_mono - ctx.last_battle_resolve_at) < 1.0:
            battle_id = sticky
            used_sticky = True
        else:
            battle_id = schedule.fetch_live_battle_id(match_id)
            ctx.last_battle_resolve_at = now_mono
            if battle_id:
                ctx.sticky_battle_by_match[match_id] = battle_id
            elif sticky:
                battle_id = sticky
                used_sticky = True
    else:
        ctx.sticky_battle_by_match[match_id] = battle_id
        ctx.last_battle_resolve_at = now_mono

    if not battle_id:
        match_info = schedule.get_match_by_id(match_id) or match
        if match_info and match_info.status == 2:
            print(f"[DONE] match={match_id} 已结束 · {match_info.display_name}")
            return "match_finished", wait_sec
        if match_info and match_info.status == 1:
            write_status(
                {
                    "state": "waiting_battle",
                    "match_id": match_id,
                    "match": match.display_name if match else match_id,
                    "message": "局间休息，等待下一局 battle_id",
                    "pipeline": "crawl||predict",
                },
                ctx,
            )
            print(f"[WAIT] match={match_id} 局间休息，等待下一局")
            return "waiting_battle", wait_sec
        write_status(
            {
                "state": "waiting_battle",
                "match_id": match_id,
                "match": match.display_name if match else match_id,
                "message": "比赛尚未生成 battle_id",
                "pipeline": "crawl||predict",
            },
            ctx,
        )
        print(f"[WAIT] match={match_id} 尚未生成 battle_id")
        return "waiting_battle", wait_sec

    if used_sticky:
        # Keep sticky quiet unless rare — print at most via status.
        pass

    history = ctx.collect_history.setdefault(battle_id, [])
    min_game_sec = 0
    if history:
        min_game_sec = int(
            history[-1].get("time_sec", 0) or history[-1].get("snapshot_time_sec", 0) or 0
        )

    raw = fetch_freshest_battle(
        battle_id,
        n_probes=args.probes,
        gap_sec=args.probe_gap,
        parallel=not args.sequential_probes,
        min_game_sec=min_game_sec,
    )
    if not raw:
        write_status(
            {
                "state": "api_error",
                "match_id": match_id,
                "battle_id": battle_id,
                "message": "battle API 不可用",
            },
            ctx,
        )
        print(f"[ERR] battle API unavailable: {battle_id}")
        return "error", wait_sec

    snap = parse_snapshot(raw.get("data", {}), battle_id)

    if not is_monotonic_snapshot(snap, history):
        prev_t = int(history[-1].get("time_sec", 0) or history[-1].get("snapshot_time_sec", 0) or 0)
        cur_t = int(snap.get("time_sec", 0) or snap.get("snapshot_time_sec", 0) or 0)
        print(
            f"[SKIP] {battle_id} 快照倒退 {cur_t}s < {prev_t}s "
            f"(tol={REWIND_ACCEPT_TOLERANCE_SEC}s)，丢弃"
        )
        return "stale_snapshot", crawl_sec

    if (
        int(snap.get("status", 0) or 0) == 2
        and history
        and int(history[-1].get("status", 0) or 0) == 2
    ):
        if ctx.sticky_battle_by_match.get(match_id) == battle_id:
            ctx.sticky_battle_by_match.pop(match_id, None)
        ctx.collect_history.pop(battle_id, None)
        ctx.last_snapshot_sec.pop(battle_id, None)
        ctx.last_frame_key.pop(battle_id, None)
        match_info = schedule.get_match_by_id(match_id)
        if match_info and match_info.status == 2:
            return "match_finished", wait_sec
        return "battle_finished", wait_sec

    ensure_battle_anchor(ctx, battle_id, snap)
    anchor = ctx.battle_anchors.get(battle_id)
    raw_lag = compute_lag_sec(snap, anchor[0], anchor[1]) if anchor else None
    prev_lag = ctx.last_lag_sec.get(battle_id)
    lag_sec, clock_jump = sanitize_lag_sec(raw_lag, prev_lag)
    if lag_sec is not None:
        ctx.last_lag_sec[battle_id] = lag_sec

    snap_sec = int(snap.get("time_sec", 0) or snap.get("snapshot_time_sec", 0) or 0)
    dedupe_key = frame_dedupe_key(snap)
    # Middle gate: only persist / enqueue unique board states.
    if ctx.last_frame_key.get(battle_id) == dedupe_key:
        return "duplicate", crawl_sec

    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    history.append(snap)
    if len(history) > 80:
        history[:] = history[-80:]
    ctx.last_snapshot_sec[battle_id] = snap_sec
    ctx.last_frame_key[battle_id] = dedupe_key

    frame_row = {
        "collected_at": collected_at,
        "match_id": match_id,
        "battle_id": battle_id,
        "minute": round(float(snap.get("minute", 0)), 2),
        "snapshot_time_sec": snap_sec,
        "lag_sec": lag_sec if lag_sec is not None else "",
        "camp1_team": snap.get("camp1_team"),
        "camp2_team": snap.get("camp2_team"),
        "gold_diff": snap.get("camp1_gold", 0) - snap.get("camp2_gold", 0),
        "kill_diff": snap.get("camp1_kill", 0) - snap.get("camp2_kill", 0),
        "tower_diff": snap.get("camp1_tower", 0) - snap.get("camp2_tower", 0),
        "status": snap.get("status"),
        "win_camp": snap.get("win_camp"),
    }
    append_frame(battle_id, frame_row)
    save_raw_snapshot_async(battle_id, raw)

    match_name = match.display_name if match else match_id
    enqueue_frame(
        ctx,
        CollectedFrame(
            match_id=match_id,
            battle_id=battle_id,
            match_name=match_name,
            collected_at=collected_at,
            raw=raw,
            snap=snap,
            lag_sec=lag_sec,
            clock_jump=clock_jump,
        ),
    )

    lag_note = (
        f" lag={lag_sec:+.0f}s"
        if isinstance(lag_sec, (int, float))
        else (" lag=clock_jump" if clock_jump else "")
    )
    print(
        f"[CRAWL] {battle_id} {frame_row['minute']:.1f}min "
        f"gold={frame_row['gold_diff']:+d}{lag_note} · next={crawl_sec}s · q={ctx.frame_queue.qsize()}"
    )

    match_info = schedule.get_match_by_id(match_id)
    if match_info and match_info.status == 2:
        return "match_finished", crawl_sec
    if int(snap.get("status", 0) or 0) == 2:
        # Finishing frame already queued for predict; only drop crawl sticky/history.
        clear_battle_runtime(ctx, match_id, battle_id)
        return "battle_finished", wait_sec
    return "running", crawl_sec


def run_once(
    args,
    artifact,
    history_by_battle: dict[str, list[dict]],
    match_id: str,
    match: ScheduleMatch | None = None,
    ctx: PipelineContext | None = None,
) -> tuple[str, float]:
    """Backward-compatible wrapper: crawl once and wait briefly for predict queue."""
    if ctx is None:
        raise RuntimeError("run_once requires PipelineContext in parallel pipeline")
    # Keep legacy history alias pointing at collect history for callers.
    history_by_battle.clear()
    history_by_battle.update(ctx.collect_history)
    outcome, poll_sec = collect_once(args, match_id, match, ctx)
    # Give predictor a short chance to drain for --once smoke runs.
    if outcome == "running":
        deadline = time.time() + 2.0
        while ctx.frame_queue.unfinished_tasks and time.time() < deadline:
            time.sleep(0.05)
    return outcome, poll_sec


def advance_to_next_match(
    schedule: ScheduleCenter,
    finished_match_id: str,
    date: str | None,
    prestart_poll: int,
    ctx: PipelineContext,
) -> tuple[str | None, ScheduleMatch | None]:
    next_match = schedule.next_match_after(finished_match_id, date=date)
    if not next_match:
        write_status(
            {
                "state": "day_complete",
                "finished_match_id": finished_match_id,
                "message": "今日赛程已全部结束",
            }
        )
        print("[WAIT] 今日赛程已全部结束")
        maybe_train_after_batch(ctx, schedule, date, reason="day_complete")
        return None, None

    write_status(
        {
            "state": "waiting_next_match",
            "finished_match_id": finished_match_id,
            "next_match_id": next_match.match_id,
            "next_match": next_match.display_name,
            "team1": next_match.team1,
            "team2": next_match.team2,
            "start_time": next_match.start_time.strftime("%Y-%m-%d %H:%M:%S") if next_match.start_time else "",
            "message": f"上一场已结束，等待 {next_match.team1} vs {next_match.team2}",
        }
    )
    print(f"[NEXT] 上一场结束，下一场 {next_match.team1} vs {next_match.team2}")
    if next_match.start_time and datetime.now() < next_match.start_time:
        switched = wait_until_start(next_match, prestart_poll, ctx, label="waiting_next_match", schedule=schedule)
        if switched:
            return switched.match_id, switched
    return next_match.match_id, next_match


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default=None, help="指定 match_id；为空则自动从赛程选择")
    parser.add_argument("--battle-id", default=None, help="指定 battle_id；为空则从 match_id 自动发现")
    parser.add_argument("--league-id", type=int, default=LEAGUE_ID)
    parser.add_argument("--collect-only", action="store_true", help="无需模型，仅采集快照和 frames，不生成胜率或自动训练")
    parser.add_argument(
        "--date",
        default=None,
        help="起始日期 YYYY-MM-DD（默认今天）。注意这是「起始偏好」不是锁定值："
             "该日比赛全部结束后会自动滚动到下一个有比赛的日期，跨天无需重启进程。",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.1,
        help="采集间隔秒（默认 0.1；仅影响爬虫，模型异步并行）",
    )
    parser.add_argument(
        "--interval-hot",
        type=float,
        default=0.1,
        help="团战期采集间隔秒（仅 --adaptive 时生效，默认 0.1）",
    )
    parser.add_argument("--hot-velocity", type=float, default=150.0, help="判定团战期的 gold_diff_velocity 阈值")
    parser.add_argument("--adaptive", action="store_true", default=False, help="按经济波动自适应间隔（默认关闭）")
    parser.add_argument("--no-adaptive", action="store_true", help="禁用自适应轮询（默认已禁用）")
    parser.add_argument("--prestart-poll", type=int, default=20, help="等待开赛时的检查间隔秒")
    parser.add_argument("--probes", type=int, default=1, help="每次采集探测 API 副本次数（高频默认 1）")
    parser.add_argument("--probe-gap", type=float, default=0.05, help="串行探测时的间隔秒")
    parser.add_argument("--sequential-probes", action="store_true", help="使用串行探测（默认并行）")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--stop-when-finished", action="store_true", help="当前局结束后停止")
    parser.add_argument("--auto-next", action="store_true", help="一场结束后自动等待并切换到下一场")
    parser.add_argument("--no-auto-next", action="store_true", help="禁用自动切换下一场")
    parser.add_argument("--auto-train", action="store_true", help="当日比赛打满后自动重训一次（默认开启）")
    parser.add_argument("--no-auto-train", action="store_true", help="禁用自动重训")
    parser.add_argument(
        "--train-after-matches",
        type=int,
        default=0,
        help="打满几场后训练；0 表示今日赛程全部结束后再训练",
    )
    args = parser.parse_args()
    if args.no_adaptive:
        args.adaptive = False

    recover_stale_train_status()

    auto_next = not args.no_auto_next and (args.auto_next or not args.match_id)
    auto_train = not args.no_auto_train and not args.collect_only

    artifact = {} if args.collect_only else load_model()
    if artifact is None:
        raise RuntimeError("未找到可用模型，请先运行 python -m kpl_insight train")

    ctx = PipelineContext(
        artifact=artifact,
        collect_only=args.collect_only,
        auto_train=auto_train,
        train_after_matches=args.train_after_matches,
        last_data_sig=realtime_data_signature(),
        collect_interval_sec=float(args.interval),
    )

    pred_thread = threading.Thread(target=predict_worker, args=(ctx,), name="kpl-predict", daemon=True)
    pred_thread.start()

    write_status(
        {
            "state": "starting",
            "model_name": artifact.get("model_name", "Unknown"),
            "auto_next": auto_next,
            "auto_train": auto_train,
            "train_after_matches": args.train_after_matches,
            "pipeline": "crawl||predict",
            "poll_interval_sec": float(args.interval),
            "probes": args.probes,
        },
        ctx,
    )
    print(
        f"[INIT] 并行流水线：爬虫 interval={args.interval}s probes={args.probes} "
        f"| 模型异步消费 queue"
    )
    history_by_battle: dict[str, list[dict]] = {}
    schedule = ScheduleCenter(args.league_id)
    current_match_id = args.match_id
    current_match: ScheduleMatch | None = None
    last_schedule_refresh = 0.0
    # args.date 只是「起始偏好」，不是锁定值：当日比赛全结束后会自动滚到下一个有比赛的日期。
    # 2026-10-18 事故就是因为 date 被钉死在启动日，进程不重启就永远找不到新比赛。
    current_date = args.date

    try:
        n = refresh_schedule_archive(args.league_id)
        print(f"[INIT] 已刷新赛程缓存 {n} 场")
        last_schedule_refresh = time.monotonic()
    except Exception as exc:
        print(f"[WARN] 赛程缓存刷新失败: {exc}")

    try:
        while True:
            try:
                if current_match_id:
                    current_match = schedule.get_match_by_id(current_match_id)
                    if not current_match:
                        current_match, picked = schedule.resolve_monitor_match_rolling(current_date)
                        if picked:
                            current_date = picked
                        if current_match:
                            current_match_id = current_match.match_id
                else:
                    current_match, picked = schedule.resolve_monitor_match_rolling(current_date)
                    if picked:
                        current_date = picked
                    if current_match:
                        current_match_id = current_match.match_id

                if not current_match:
                    write_status({"state": "waiting_schedule", "message": "暂无可监控比赛"}, ctx)
                    print("[WAIT] 暂无可监控比赛")
                    maybe_train_after_batch(ctx, schedule, current_date, reason="waiting_schedule")
                    if args.once:
                        break
                    time.sleep(args.prestart_poll)
                    continue

                current_match_id = current_match.match_id
                if current_match.start_time and datetime.now() < current_match.start_time:
                    switched = wait_until_start(current_match, args.prestart_poll, ctx, schedule=schedule)
                    if switched:
                        current_match = switched
                        current_match_id = switched.match_id
                        current_date = switched.start_time.strftime("%Y-%m-%d") if switched.start_time else current_date

                cycle_args = argparse.Namespace(
                    league_id=args.league_id,
                    match_id=current_match_id,
                    battle_id=None,
                    date=current_date,
                    probes=args.probes,
                    probe_gap=args.probe_gap,
                    sequential_probes=args.sequential_probes,
                    interval=args.interval,
                    interval_hot=args.interval_hot,
                    hot_velocity=args.hot_velocity,
                    adaptive=args.adaptive,
                )
                t0 = time.monotonic()
                outcome, poll_sec = collect_once(cycle_args, current_match_id, current_match, ctx)
                history_by_battle = ctx.collect_history

                if outcome == "match_finished":
                    maybe_train_after_batch(ctx, schedule, current_date, reason="match_finished")
                    if time.monotonic() - last_schedule_refresh > 1800:
                        try:
                            refresh_schedule_archive(args.league_id)
                            last_schedule_refresh = time.monotonic()
                        except Exception:
                            pass

                if args.once or (outcome in {"battle_finished", "match_finished"} and args.stop_when_finished):
                    break

                if outcome == "match_finished" and auto_next:
                    next_match_id, next_match = advance_to_next_match(
                        schedule, current_match_id, current_date, args.prestart_poll, ctx
                    )
                    if next_match_id:
                        current_match_id = next_match_id
                        current_match = next_match
                        args.battle_id = None
                        continue
                    if args.once:
                        break
                    time.sleep(args.prestart_poll)
                    current_match_id = None
                    continue

                # Pace crawl by wall clock: subtract time spent in collect_once.
                elapsed = time.monotonic() - t0
                sleep_sec = max(0.0, float(poll_sec) - elapsed)
                if sleep_sec > 0:
                    time.sleep(sleep_sec)
            except KeyboardInterrupt:
                write_status({"state": "stopped", "message": "用户中断"}, ctx)
                print("\n[STOP] monitor interrupted")
                break
            except Exception as exc:
                write_status({"state": "error", "message": f"cycle error: {exc}"}, ctx)
                print(f"[ERR] cycle crashed: {exc}")
                import traceback

                traceback.print_exc()
                time.sleep(max(5.0, float(args.interval)))
    finally:
        ctx.stop_event.set()
        try:
            ctx.frame_queue.put_nowait(_SENTINEL)
        except queue.Full:
            pass
        pred_thread.join(timeout=3.0)


if __name__ == "__main__":
    main()
