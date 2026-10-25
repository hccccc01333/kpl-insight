"""Small synthetic example. No network, real match data, trained weights or forecast claims."""
import argparse
import csv
import json
from pathlib import Path

from kpl_insight.core import FeatureBuilder, detect_events, parse_snapshot
from kpl_insight.paths import PROJECT_ROOT


def synthetic_payloads():
    """A fictitious game changes economy direction; values are hand-authored fixtures."""
    for minute in range(1, 13):
        lead = (minute - 6) * 350
        total = 2400 * minute + 1200
        camps = {}
        for camp in (1, 2):
            kills = max(0, minute // 2 + (2 if camp == 1 and minute >= 8 else 0))
            camps[f"camp{camp}"] = {
                "team_name": f"示例战队{camp}",
                "gold": total + (lead if camp == 1 else -lead),
                "kill_num": kills, "assist_num": kills * 2, "death_num": minute // 2,
                "push_tower_num": min(8, minute // (3 if camp == 1 else 4)),
                "kill_tyrant_num": int(minute >= (5 if camp == 1 else 9)),
            }
        yield {
            "game_duration": minute * 60 * 1000,
            "status": 2 if minute == 12 else 1,
            "win_camp": 1 if minute == 12 else 0,
            "battle_player_list": [],
            **camps,
        }


def run_demo(destination: Path) -> dict:
    snapshots = [parse_snapshot(payload, "synthetic-demo") for payload in synthetic_payloads()]
    builder = FeatureBuilder()
    rows = [builder.build(snapshot, snapshots[:i]) for i, snapshot in enumerate(snapshots)]
    events = detect_events(snapshots)
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "features.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (destination / "snapshots.json").write_text(json.dumps(snapshots, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {
        "synthetic": True, "trained_model_used": False,
        "description": "虚构对局，仅验证解析与特征流程，不代表真实赛事或预测能力。",
        "snapshots": len(snapshots), "features": len(rows[0]), "events": events,
        "first_gold_diff": rows[0]["gold_diff"], "last_gold_diff": rows[-1]["gold_diff"],
    }
    (destination / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "output" / "demo")
    args = parser.parse_args()
    result = run_demo(args.output)
    print(result["description"])
    print(f"{result['snapshots']} snapshots / {result['features']} features / {len(result['events'])} events")
    print(f"output: {args.output.resolve()}")


if __name__ == "__main__":
    main()
