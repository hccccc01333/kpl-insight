"""Offline tests for the public package, data bridge and model split contract."""
import csv
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

REPO = Path(__file__).resolve().parents[1]
RUN = REPO / "output" / "test-runs" / uuid.uuid4().hex
RUN.mkdir(parents=True)
os.environ["KPL_DATA_ROOT"] = str(RUN)

import pandas as pd

from kpl_insight.core import FeatureBuilder, load_holdout_badge_metrics, parse_snapshot
from kpl_insight.demo import run_demo, synthetic_payloads
from kpl_insight.models.train import build_causal_team_winrate_maps, split_train_calib_test


class DataPipelineTests(unittest.TestCase):
    def test_demo_is_offline_and_marks_synthetic_data(self):
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network call")):
            result = run_demo(RUN / "demo")
        self.assertTrue(result["synthetic"])
        self.assertFalse(result["trained_model_used"])
        self.assertEqual(result["snapshots"], 12)
        self.assertLess(result["first_gold_diff"], 0)
        self.assertGreater(result["last_gold_diff"], 0)
        self.assertTrue((RUN / "demo/features.csv").is_file())

    def test_features_do_not_depend_on_final_winner_label(self):
        payload = list(synthetic_payloads())[5]
        first = parse_snapshot(payload)
        second = parse_snapshot({**payload, "win_camp": 2})
        self.assertEqual(first["time_sec"], 360)
        self.assertEqual(FeatureBuilder().build(first), FeatureBuilder().build(second))

    def test_train_calibration_test_are_disjoint_and_time_ordered(self):
        rows = [{"battle_id": f"fixture_{i:04d}"} for i in range(180)]
        train, calibration, test = split_train_calib_test(rows)
        self.assertEqual(train + calibration + test, rows)
        groups = [{item["battle_id"] for item in group} for group in (train, calibration, test)]
        self.assertTrue(all(groups))
        self.assertFalse(groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])

    def test_team_prior_does_not_see_current_or_future_result(self):
        rows = pd.DataFrame([
            {"battle_id": "fixture_1", "camp1_team_name": "A", "camp2_team_name": "B", "win_camp": 1},
            {"battle_id": "fixture_2", "camp1_team_name": "A", "camp2_team_name": "B", "win_camp": 1},
        ])
        before, _ = build_causal_team_winrate_maps(rows)
        rows.loc[1, "win_camp"] = 2
        after, _ = build_causal_team_winrate_maps(rows)
        self.assertEqual(before, after)
        self.assertEqual(before["fixture_1"]["A"], 0.5)
        self.assertGreater(before["fixture_2"]["A"], 0.5)

    def test_no_model_does_not_display_historical_performance(self):
        badge = load_holdout_badge_metrics()
        self.assertEqual(badge["source"], "unavailable")
        self.assertIsNone(badge["all_brier"])

    def test_collect_only_does_not_enqueue_predictions(self):
        from kpl_insight.collection.monitor import CollectedFrame, PipelineContext, enqueue_frame
        context = PipelineContext(artifact={}, collect_only=True, auto_train=False)
        frame = CollectedFrame("match", "battle", "fixture", "2026-01-01", {}, {"time_sec": 60, "minute": 1}, None, False)
        self.assertTrue(enqueue_frame(context, frame))
        self.assertTrue(context.frame_queue.empty())
        self.assertFalse(context.deduped_timeline)

    def test_package_modules_import_without_network(self):
        from kpl_insight.cli import COMMANDS
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network call")):
            for module, _ in COMMANDS.values():
                importlib.import_module(module)

    def test_dataset_generates_training_compatible_tables(self):
        destination = RUN / "tables"
        raw_dir = destination / "data/realtime/raw_snapshots/fixture_1700000000"
        raw_dir.mkdir(parents=True)
        for i, payload in enumerate(synthetic_payloads()):
            payload["battle_player_list"] = [
                {"camp": camp, "team_name": f"示例战队{camp}", "player_name": f"P{camp}-{position}",
                 "position": position, "gold": 4000, "kill_num": 1, "death_num": 1, "assist_num": 1,
                 "hurt_to_hero_total": 3000, "be_hurt_by_hero_total": 2000}
                for camp in (1, 2) for position in (2, 4, 5, 6, 7)
            ]
            (raw_dir / f"{i:03d}.json").write_text(json.dumps({"code": 200, "data": payload}), encoding="utf-8")
        archive = raw_dir.parents[1] / "schedule_archive.csv"
        with archive.open("w", encoding="utf-8", newline="") as handle:
            fields = ["league_id", "match_id", "date", "start_time", "team1", "team2", "stage", "bo_type", "battle_ids"]
            writer = csv.DictWriter(handle, fields)
            writer.writeheader()
            writer.writerow(dict(zip(fields, ["fixture", "demo", "2026-01-01", "2026-01-01 12:00:00",
                                                "示例战队1", "示例战队2", "fixture", "1", raw_dir.name])))
        env = {**os.environ, "KPL_DATA_ROOT": str(destination), "PYTHONIOENCODING": "utf-8"}
        code = ("from unittest.mock import patch; "
                "from kpl_insight.datasets.build import build; "
                "guard=patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected network')); "
                "guard.start(); build()")
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        battles = pd.read_csv(destination / "data/processed/battles.csv")
        players = pd.read_csv(destination / "data/processed/players.csv")
        self.assertEqual(len(battles), 1)
        self.assertEqual(int(battles.iloc[0]["game_duration"]), 720000)
        self.assertEqual(int(battles.iloc[0]["win_camp"]), 1)
        self.assertEqual(battles.iloc[0]["camp1_team_name"], "示例战队1")
        self.assertEqual(len(players), 10)
        self.assertEqual(set(players["position"]), {2, 4, 5, 6, 7})
        self.assertTrue((destination / "data/analysis/battles.csv").is_file())


if __name__ == "__main__":
    unittest.main()
