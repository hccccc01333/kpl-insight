# -*- coding: utf-8 -*-
"""直播展示层：早期区间、低置信状态、EMA 平滑与资源刷新窗口。

这里只做"怎么展示"，不改模型概率本身：
  - 前 5 分钟样本不足：不给单点胜率，只给区间；
  - 5–8 分钟与资源刷新窗口：低置信，给区间并标注；
  - 2–3 分钟 EMA + 每分钟限速，避免 20 秒内几十个点的抖动；
  - 资源窗口来自 2026-10 最近 24 局的实测击杀时间（暴君 ~4.1–5.1′，
    暗影暴君 ~10.2–11.4′，主宰 ~12′，风暴 ~20′），按"估算窗口"展示。
"""
from __future__ import annotations

import json
from pathlib import Path

from kpl_insight.paths import PROJECT_ROOT

CALIB_PATH = PROJECT_ROOT / "output" / "models" / "display_calibrators_v2.json"

# 实测窗口：不是官方公告的刷新表，而是当前版本最近比赛的实际争夺区间。
OBJECTIVE_WINDOWS = [
    (3.8, 5.4, "首条暴君"),
    (7.8, 9.2, "第二条暴君"),
    (10.0, 11.4, "暗影暴君"),
    (12.0, 13.2, "主宰 / 暗影资源"),
    (15.0, 16.2, "资源刷新"),
    (17.5, 18.7, "资源刷新"),
    (19.8, 21.0, "风暴龙王"),
]

EARLY_INSUFFICIENT_MIN = 5.0
EARLY_LOW_CONF_MIN = 8.0
EARLY_CLIP = (0.30, 0.70)
EMA_HALF_LIFE_SEC = 90.0
MAX_STEP_PER_MIN = 0.10
MAX_DIVERGENCE = 0.12   # 平滑值最多偏离当前原始值 12pp，避免"模型 57%、页面 74%"


def model_fingerprint(artifact: dict | None) -> str | None:
    """与 calibrate_replay.py / regression_replay_vs_live.py 相同的模型指纹。"""
    if not artifact:
        return None
    return f"{artifact.get('version')}|{artifact.get('trained_at')}|{len(artifact.get('feature_columns') or [])}"


def load_calibrator(path: Path = CALIB_PATH, model_fp: str | None = None) -> dict | None:
    """加载 calibrate_replay.py 的分阶段校准表；指纹不匹配时拒绝使用。

    calibration_v2 是拟合在某一版模型重放概率上的；模型重训后继续套旧表，
    等于把旧模型的校准曲线硬贴到新模型上。因此这里只接受同 fingerprint 的表。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if model_fp and data.get("model_fp") != model_fp:
        return None
    return data


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    if not xs:
        return x
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            span = xs[i] - xs[i - 1]
            t = 0.0 if span <= 0 else (x - xs[i - 1]) / span
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def prior_weight(minute: float, gold_diff: float) -> float:
    """赛前先验的权重：前 2 分钟满权重，6 分钟线性降到 0；金差越大越早让位。

    178 局重放验证（2026 时段）：衰减到 6 分钟时 0–4′ Brier 0.2279→0.2140，
    4–8′ 基本持平；衰减到 10 分钟会把 4–8′ Brier 拉高到 0.1719（比不用先验更差）。
    """
    time_w = 1.0 if minute <= 2.0 else max(0.0, (6.0 - minute) / 4.0)
    state_w = 1.0 / (1.0 + (abs(float(gold_diff)) / 2500.0) ** 2)
    return float(max(0.0, min(1.0, time_w * state_w)))


def blend_prior(p: float, minute: float, prior: float | None, gold_diff: float) -> tuple[float, float]:
    """把赛前先验（camp1 视角）按时间/局内状态融合进模型概率。"""
    if prior is None:
        return float(p), 0.0
    w = prior_weight(minute, gold_diff)
    return float(w * float(prior) + (1.0 - w) * float(p)), w


def calibrate_probability(p: float, minute: float, calib: dict | None) -> float:
    """按阶段应用后校准表；没有表或阶段缺失时原样返回。"""
    if not calib:
        return float(p)
    phase = "early" if minute <= 8 else ("mid" if minute < 15 else "late")
    table = (calib.get("phases") or {}).get(phase)
    if not table:
        return float(p)
    x = min(max(float(p), 1e-6), 1 - 1e-6)
    if table.get("kind") == "isotonic":
        return float(min(max(_interp(x, table.get("x") or [], table.get("y") or []), 0.02), 0.98))
    z = __import__("math").log(x / (1 - x))
    a, b = float(table.get("a", 1.0)), float(table.get("b", 0.0))
    return float(min(max(1.0 / (1.0 + __import__("math").exp(-(a * z + b))), 0.02), 0.98))


def objective_window(minute: float) -> tuple[bool, str]:
    """当前分钟是否落在资源争夺窗口（按实测时间估算）。"""
    try:
        m = float(minute)
    except (TypeError, ValueError):
        return False, ""
    for lo, hi, label in OBJECTIVE_WINDOWS:
        if lo <= m < hi:
            return True, label
    return False, ""


def ema_smooth(points: list[tuple[float, float]],
               half_life_sec: float = EMA_HALF_LIFE_SEC,
               max_step_per_min: float = MAX_STEP_PER_MIN) -> list[tuple[float, float]]:
    """按时间做 EMA，并限制每分钟最大变化。

    points: [(minute, prob)]，按分钟升序。
    返回同样长度的 [(minute, smoothed_prob)]。
    """
    out: list[tuple[float, float]] = []
    for minute, prob in points:
        try:
            m = float(minute)
            p = min(max(float(prob), 0.02), 0.98)
        except (TypeError, ValueError):
            continue
        if not out:
            out.append((m, p))
            continue
        prev_m, prev_p = out[-1]
        dt_min = max(m - prev_m, 0.01)
        alpha = 1.0 - 0.5 ** (dt_min * 60.0 / max(half_life_sec, 1.0))
        smoothed = prev_p + alpha * (p - prev_p)
        max_step = max_step_per_min * dt_min
        smoothed = min(max(smoothed, prev_p - max_step), prev_p + max_step)
        # 不允许平滑值离当前原始值太远：防止"模型已经 57%，页面还挂 74%"
        smoothed = min(max(smoothed, p - MAX_DIVERGENCE), p + MAX_DIVERGENCE)
        out.append((m, smoothed))
    return out


def display_state(minute: float, objective: bool, n_points: int) -> str:
    """insufficient = 样本不足；low_confidence = 低置信；normal = 正常。"""
    if n_points < 3 or minute < EARLY_INSUFFICIENT_MIN:
        return "insufficient"
    if minute < EARLY_LOW_CONF_MIN or objective or n_points < 4:
        return "low_confidence"
    return "normal"


def band_width(minute: float, objective: bool) -> float:
    if minute < 4:
        width = 0.12
    elif minute < 8:
        width = 0.09
    elif minute < 12:
        width = 0.06
    else:
        width = 0.05
    if objective:
        width += 0.04
    return width


def build_display(minute: float, raw_prob: float, smooth_prob: float | None,
                  objective: bool, objective_label: str, n_points: int) -> dict:
    """生成前端直接消费的 display 对象。"""
    p = smooth_prob if smooth_prob is not None else raw_prob
    state = display_state(float(minute), bool(objective), int(n_points))
    if float(minute) < EARLY_LOW_CONF_MIN:
        p = min(max(float(p), EARLY_CLIP[0]), EARLY_CLIP[1])
    width = band_width(float(minute), bool(objective))
    lo = max(0.03, p - width)
    hi = min(0.97, p + width)
    if float(minute) < EARLY_LOW_CONF_MIN:
        lo = max(EARLY_CLIP[0], lo)
        hi = min(EARLY_CLIP[1], hi)

    if state == "insufficient":
        note = "开局样本不足，模型仍在观察"
    elif objective:
        note = f"{objective_label}窗口，模型不确定性偏高"
    elif state == "low_confidence":
        note = "样本仍偏少，仅供参考"
    else:
        note = ""

    return {
        "state": state,
        "prob": None if state == "insufficient" else round(float(p), 4),
        "lo": round(float(lo), 4),
        "hi": round(float(hi), 4),
        "raw": round(float(raw_prob), 4),
        "minute": round(float(minute), 1),
        "points": int(n_points),
        "objective_window": bool(objective),
        "objective_label": objective_label,
        "note": note,
    }
