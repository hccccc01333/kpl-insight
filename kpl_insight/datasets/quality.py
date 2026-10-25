"""
Classify realtime battle dirs into clean vs quarantine datasets.

Does NOT move or delete raw_snapshots. Optionally copies into datasets/clean
and datasets/quarantine.

Usage:
    python -m kpl_insight.datasets.quality --dry-run
    python -m kpl_insight.datasets.quality --materialize
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import pandas as pd

from kpl_insight.core import (
    CLEAN_DIR,
    DATASETS_DIR,
    QUARANTINE_DIR,
    RAW_DIR,
    load_battle_jsons,
)


MIN_SNAPS = 5
MIN_MINUTES = 8
MAX_BACKWARD_JUMP_SEC = 60


def _count_json_files(battle_dir: Path) -> tuple[int, int, int, int]:
    """Return (total_json, live_json, backfill_json, bad_json)."""
    total = live = backfill = bad = 0
    for path in battle_dir.glob("*.json"):
        total += 1
        if path.name.startswith("backfill_"):
            backfill += 1
        else:
            live += 1
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            bad += 1
    return total, live, backfill, bad


def _resolve_win_camp(snaps: list[dict[str, Any]]) -> tuple[int, bool]:
    """Return (win_camp, has_finished_status)."""
    has_finished = False
    win_camp = 0
    for snap in reversed(snaps):
        if int(snap.get("status", 0) or 0) == 2:
            has_finished = True
        wc = int(snap.get("win_camp", 0) or 0)
        if wc in (1, 2) and win_camp == 0:
            win_camp = wc
    return win_camp, has_finished


def _time_monotonic_ok(snaps: list[dict[str, Any]]) -> tuple[bool, float]:
    """Check time_sec is mostly non-decreasing; return (ok, max_backward_jump)."""
    if len(snaps) < 2:
        return True, 0.0
    max_jump = 0.0
    prev = float(snaps[0].get("time_sec", 0) or 0)
    for snap in snaps[1:]:
        cur = float(snap.get("time_sec", 0) or 0)
        if cur + 1e-6 < prev:
            jump = prev - cur
            max_jump = max(max_jump, jump)
        prev = max(prev, cur)
    return max_jump <= MAX_BACKWARD_JUMP_SEC, max_jump


def classify_battle_dir(battle_dir: Path) -> dict[str, Any]:
    battle_id = battle_dir.name
    total_json, live_json, backfill_json, bad_json = _count_json_files(battle_dir)
    snaps = load_battle_jsons(battle_dir)
    n_snaps = len(snaps)
    minutes = {max(int(s.get("minute", s.get("minute_bin", 0)) or 0), 1) for s in snaps}
    n_minutes = len(minutes)
    win_camp, has_finished = _resolve_win_camp(snaps)
    mono_ok, max_jump = _time_monotonic_ok(snaps)

    reasons: list[str] = []
    if total_json == 0:
        reasons.append("no_json_files")
    if bad_json > 0 and bad_json >= max(1, total_json // 2):
        reasons.append(f"many_bad_json:{bad_json}/{total_json}")
    if n_snaps < MIN_SNAPS:
        reasons.append(f"too_few_snaps:{n_snaps}<{MIN_SNAPS}")
    if win_camp not in (1, 2):
        reasons.append("missing_win_camp")
    if n_minutes < MIN_MINUTES:
        reasons.append(f"too_few_minutes:{n_minutes}<{MIN_MINUTES}")
    if live_json == 0 and backfill_json > 0:
        reasons.append("backfill_only")
    if live_json == 0 and n_snaps < MIN_SNAPS:
        reasons.append("shallow_or_empty")
    if not mono_ok:
        reasons.append(f"clock_backjump:{max_jump:.0f}s")

    bucket = "clean" if not reasons else "quarantine"
    return {
        "battle_id": battle_id,
        "bucket": bucket,
        "reasons": reasons,
        "reasons_str": ";".join(reasons),
        "n_json_total": total_json,
        "n_json_live": live_json,
        "n_json_backfill": backfill_json,
        "n_json_bad": bad_json,
        "n_snaps": n_snaps,
        "n_minutes": n_minutes,
        "win_camp": win_camp,
        "has_finished_status": has_finished,
        "max_backward_jump_sec": round(max_jump, 1),
        "minute_min": min(minutes) if minutes else None,
        "minute_max": max(minutes) if minutes else None,
    }


def scan_raw() -> list[dict[str, Any]]:
    if not RAW_DIR.exists():
        return []
    rows = []
    for battle_dir in sorted([p for p in RAW_DIR.iterdir() if p.is_dir()], key=lambda p: p.name):
        rows.append(classify_battle_dir(battle_dir))
    return rows


def write_catalog(rows: list[dict[str, Any]]) -> dict[str, Any]:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    clean_rows = [r for r in rows if r["bucket"] == "clean"]
    quar_rows = [r for r in rows if r["bucket"] == "quarantine"]
    catalog = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": str(RAW_DIR),
        "rules": {
            "min_snaps": MIN_SNAPS,
            "min_minutes": MIN_MINUTES,
            "max_backward_jump_sec": MAX_BACKWARD_JUMP_SEC,
            "require_live_json": True,
            "require_win_camp": True,
        },
        "stats": {
            "total": len(rows),
            "clean": len(clean_rows),
            "quarantine": len(quar_rows),
        },
        "battles": rows,
    }
    (DATASETS_DIR / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    cols = [
        "battle_id",
        "bucket",
        "reasons_str",
        "n_snaps",
        "n_minutes",
        "win_camp",
        "has_finished_status",
        "n_json_total",
        "n_json_live",
        "n_json_backfill",
        "n_json_bad",
        "max_backward_jump_sec",
        "minute_min",
        "minute_max",
    ]
    pd.DataFrame(clean_rows if clean_rows else [], columns=cols).to_csv(
        DATASETS_DIR / "clean_manifest.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(quar_rows if quar_rows else [], columns=cols).to_csv(
        DATASETS_DIR / "quarantine_manifest.csv", index=False, encoding="utf-8-sig"
    )
    return catalog


def materialize(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Copy into empty destinations only; preserve any existing datasets unchanged."""
    destinations = (CLEAN_DIR, QUARANTINE_DIR)
    for root in destinations:
        if root.exists() and any(root.iterdir()):
            raise FileExistsError(
                f"Existing dataset preserved: {root}. Use --dry-run to refresh manifests, "
                "or archive the existing materialized directories before rebuilding."
            )
    for root in destinations:
        root.mkdir(parents=True, exist_ok=True)
    copied = {"clean": 0, "quarantine": 0}
    for row in rows:
        src = RAW_DIR / row["battle_id"]
        if not src.is_dir():
            continue
        dst_root = CLEAN_DIR if row["bucket"] == "clean" else QUARANTINE_DIR
        shutil.copytree(src, dst_root / row["battle_id"])
        copied[row["bucket"]] += 1
    return copied


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify raw_snapshots into clean/quarantine")
    parser.add_argument("--dry-run", action="store_true", help="write manifests only, no copy")
    parser.add_argument("--materialize", action="store_true", help="copy into clean/ and quarantine/")
    args = parser.parse_args()
    if not args.dry_run and not args.materialize:
        # Default to inspection; copying must be explicit.
        args.dry_run = True

    print(f"scanning {RAW_DIR} ...")
    rows = scan_raw()
    catalog = write_catalog(rows)
    stats = catalog["stats"]
    print(f"total={stats['total']} clean={stats['clean']} quarantine={stats['quarantine']}")
    print(f"catalog: {DATASETS_DIR / 'catalog.json'}")
    print(f"clean_manifest: {DATASETS_DIR / 'clean_manifest.csv'}")
    print(f"quarantine_manifest: {DATASETS_DIR / 'quarantine_manifest.csv'}")

    if args.dry_run and not args.materialize:
        print("dry-run: skip materialize")
        return

    if args.materialize:
        print("materializing copies ...")
        copied = materialize(rows)
        print(f"copied clean={copied['clean']} quarantine={copied['quarantine']}")
        print(f"clean_dir={CLEAN_DIR}")
        print(f"quarantine_dir={QUARANTINE_DIR}")


if __name__ == "__main__":
    main()
