# -*- coding: utf-8 -*-
"""Run the fixed 10-series Series Intelligence V1 benchmark.

The expected values are generated from the official schedule + game-detail
assets and committed in benchmark/series_benchmark.json. The runner uses the
same public reader as the CLI; it does not reuse the expected values as input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kpl_insight.analysis import analyze_series, load_series  # noqa: E402
from kpl_insight.analysis.loaders import DEFAULT_SITE_DIR  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-dir", default=str(DEFAULT_SITE_DIR))
    ap.add_argument("--config", default=str(ROOT / "benchmark" / "series_benchmark.json"))
    args = ap.parse_args()
    expected = json.loads(Path(args.config).read_text(encoding="utf-8"))
    failures = []
    for exp in expected:
        mid = exp["match_id"]
        try:
            series = load_series(mid, args.site_dir)
        except Exception as exc:
            failures.append(f"{mid}: load failed: {exc}")
            print(f"FAIL {mid} load: {exc}")
            continue
        errors = []
        if (series.team1, series.team2) != (exp["team1"], exp["team2"]):
            errors.append(f"teams {series.team1}/{series.team2}")
        if (series.score1, series.score2) != (exp["score1"], exp["score2"]):
            errors.append(f"score {series.score1}:{series.score2}")
        if series.bo != exp["bo"]:
            errors.append(f"bo {series.bo}")
        if len(series.games) != len(exp["games"]):
            errors.append(f"game count {len(series.games)}")
        by_seq = {g.seq: g for g in series.games}
        for eg in exp["games"]:
            g = by_seq.get(eg["seq"])
            if not g:
                errors.append(f"missing G{eg['seq']}")
                continue
            if g.battle_id != eg["battle_id"]:
                errors.append(f"G{eg['seq']} battle_id")
            if g.team1 != eg["team1"] or g.team2 != eg["team2"]:
                errors.append(f"G{eg['seq']} side teams")
            if g.winner != eg["winner"]:
                errors.append(f"G{eg['seq']} winner {g.winner}")
            if abs(g.duration - float(eg["duration"])) > 0.01:
                errors.append(f"G{eg['seq']} duration")
            if g.side_of(g.team1) != 1 or g.side_of(g.team2) != 2:
                errors.append(f"G{eg['seq']} side ordinal")
        try:
            report = analyze_series(series)
            if report.get("schema_version") != "1.0":
                errors.append("report schema")
            if len(report.get("games", [])) != len(series.games):
                errors.append("report games")
        except Exception as exc:
            errors.append(f"analyze failed: {exc}")
        if errors:
            failures.append(f"{mid}: " + "; ".join(errors))
            print(f"FAIL {mid}: " + "; ".join(errors))
        else:
            print(f"PASS {mid} · {series.team1} {series.score1}:{series.score2} {series.team2} · "
                  f"{len(series.games)} 局 · {report['data_quality']['status']}")

    print(f"\n{len(expected) - len(failures)}/{len(expected)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
