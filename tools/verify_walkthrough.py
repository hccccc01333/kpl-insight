"""Verify the published aggregate excerpt without weights or network access."""

import argparse
import json
import math
from pathlib import Path


DEFAULT_SAMPLE = Path(__file__).resolve().parents[1] / "docs/examples/real-snapshot-excerpt.json"


def verify_sample(sample):
    raw = sample["api_excerpt"]
    prediction = sample["historical_prediction"]
    frame = sample["site_frame"]
    first = raw["camp1"]
    second = raw["camp2"]
    seconds = int(raw["game_duration"]) // 1000
    minute_bin = max(seconds // 60, 1)
    gold_diff = first["gold"] - second["gold"]
    kill_diff = first["kill_num"] - second["kill_num"]
    tower_diff = first["push_tower_num"] - second["push_tower_num"]
    checks = {
        "game time": seconds == int(prediction["snapshot_time_sec"]),
        "gold difference": gold_diff == int(prediction["gold_diff"]) == frame["gd"],
        "kill difference": kill_diff == int(prediction["kill_diff"]) == frame["k"][0] - frame["k"][1],
        "tower difference": tower_diff == int(prediction["tower_diff"]) == frame["t"][0] - frame["t"][1],
        "site time rounding": math.isclose(round(seconds / 60, 1), frame["m"]),
        "in-progress record": raw["status"] == 1 and raw["win_camp"] == 0,
        "historical provenance": "historical" in sample["provenance"]["probability_kind"],
    }
    probability = float(prediction["camp1_win_prob"])
    complement = float(prediction["camp2_win_prob"])
    checks["probability range"] = 0 <= probability <= 1 and 0 <= complement <= 1
    checks["probability sum"] = math.isclose(probability + complement, 1)
    checks["site probability rounding"] = math.isclose(round(probability, 3), frame["p"])
    winner_camp = sample["official_result"]["win_camp"]
    checks["winner camp"] = winner_camp in (1, 2)
    winner = raw.get(f"camp{winner_camp}", {}).get("team_name")
    checks["winner identity"] = winner == sample["official_result"]["winner"]
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("Inconsistent excerpt: " + ", ".join(failed))
    outcome = int(winner_camp == 1)
    return {
        "scope": "aggregate arithmetic, record alignment and one-point error only; not model reproduction",
        "checks": len(checks),
        "parsed": {"snapshot_time_sec": seconds, "minute_bin": minute_bin},
        "selected_features": {
            "gold_diff": gold_diff,
            "gold_diff_per_min": gold_diff / minute_bin,
            "gold_ratio": gold_diff / (first["gold"] + second["gold"]),
            "kill_diff_per_min": kill_diff / minute_bin,
            "tower_diff": tower_diff,
        },
        "historical_camp1_probability": probability,
        "camp1_outcome": outcome,
        "direction_correct_at_this_point": (probability >= 0.5) == bool(outcome),
        "one_point_brier": (probability - outcome) ** 2,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    args = parser.parse_args()
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    print(json.dumps(verify_sample(sample), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
