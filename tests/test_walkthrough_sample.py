import copy
import json
from pathlib import Path
import runpy
import unittest


ROOT = Path(__file__).resolve().parents[1]
VERIFY = runpy.run_path(str(ROOT / "tools/verify_walkthrough.py"))["verify_sample"]


class WalkthroughSampleTests(unittest.TestCase):
    def setUp(self):
        self.sample = json.loads((ROOT / "docs/examples/real-snapshot-excerpt.json").read_text(encoding="utf-8"))

    def test_selected_real_fields_and_historical_prediction_align(self):
        result = VERIFY(self.sample)
        self.assertEqual(result["parsed"]["snapshot_time_sec"], 767)
        self.assertEqual(result["selected_features"]["gold_diff"], 4297)
        self.assertFalse(result["direction_correct_at_this_point"])
        self.assertAlmostEqual(result["one_point_brier"], 0.94804 ** 2)

    def test_modified_aggregate_is_rejected(self):
        modified = copy.deepcopy(self.sample)
        modified["api_excerpt"]["camp1"]["gold"] += 1
        with self.assertRaisesRegex(ValueError, "gold difference"):
            VERIFY(modified)

    def test_wrong_probability_complement_is_rejected(self):
        self.sample["historical_prediction"]["camp2_win_prob"] = "0.8"
        with self.assertRaisesRegex(ValueError, "probability sum"):
            VERIFY(self.sample)

    def test_wrong_winner_identity_is_rejected(self):
        self.sample["official_result"]["winner"] = "广州TTG"
        with self.assertRaisesRegex(ValueError, "winner identity"):
            VERIFY(self.sample)


if __name__ == "__main__":
    unittest.main()
