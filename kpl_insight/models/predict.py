"""
KPL 实时预测薄封装（统一走 kpl_official_core）

生产采集请用：
    python -m kpl_insight.collection.monitor --interval 3

本脚本仅提供单局离线/一次性预测，避免再维护第二套特征工程。
"""

from __future__ import annotations

import argparse
import sys
from collections import deque
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from kpl_insight.core import (
    PREDICTION_DIR,
    RAW_DIR,
    fetch_freshest_battle,
    load_battle_jsons,
    load_model,
    parse_snapshot,
    predict_probability,
    prediction_confidence,
)


def predict_battle(battle_id: str, from_raw: bool = True) -> None:
    artifact = load_model()
    if not artifact:
        raise SystemExit("未找到可用模型（优先 v9_official_platform.joblib）")

    history: deque = deque(maxlen=40)
    if from_raw and (RAW_DIR / battle_id).exists():
        snaps = load_battle_jsons(RAW_DIR / battle_id)
        print(f"从本地 raw 回放 {battle_id} · {len(snaps)} 个快照 · 模型={artifact.get('model_name')}")
        for snap in snaps:
            prob, feats, explain = predict_probability(artifact, snap, list(history))
            history.append(snap)
            conf = prediction_confidence(snap.get("minute_bin", 1), prob, artifact)
            top = explain[0]["factor"] if explain else ""
            badge = "LOW" if conf["low_confidence"] else conf["confidence"]
            print(
                f"  {float(snap.get('minute', 0)):5.1f}min  "
                f"P(camp1)={prob:.3f}  [{badge}]  {top}"
            )
        return

    raw = fetch_freshest_battle(battle_id, n_probes=3, gap_sec=0.2)
    if not raw:
        raise SystemExit(f"无法拉取 battle API: {battle_id}")
    snap = parse_snapshot(raw.get("data", {}), battle_id)
    prob, feats, explain = predict_probability(artifact, snap, [])
    conf = prediction_confidence(snap.get("minute_bin", 1), prob, artifact)
    print(f"live {battle_id} @ {snap.get('minute'):.1f}min")
    print(f"  {snap.get('camp1_team')} {prob:.1%} vs {snap.get('camp2_team')} {1-prob:.1%}")
    print(f"  confidence={conf['confidence']} · {conf['reason']}")
    print(f"  top_factor={(explain[0]['factor'] if explain else '')}")
    print(f"  predictions dir: {PREDICTION_DIR}")


def main():
    parser = argparse.ArgumentParser(description="Thin predict wrapper over kpl_official_core")
    parser.add_argument("--battle-id", required=True)
    parser.add_argument("--live", action="store_true", help="忽略本地 raw，直接打官方 API")
    args = parser.parse_args()
    predict_battle(args.battle_id, from_raw=not args.live)


if __name__ == "__main__":
    main()
