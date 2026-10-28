"""Exercise real, harmless workers; never start the live collector in tests."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import uuid

from kpl_insight.local_runtime import RuntimeControl

ROOT = Path(__file__).resolve().parents[1]


class LocalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / "output/local-runtime-tests" / uuid.uuid4().hex
        self.site = self.root / "site"
        self.site.mkdir(parents=True)
        self.control = RuntimeControl(self.site, self.root)

    def tearDown(self):
        self.control.stop()

    def safe_worker(self, mode, league):
        worker = [sys.executable, "-u", "-c", "import time; print('worker ready', flush=True); time.sleep(300)"]
        return {"collector": worker, **({"exporter": worker} if mode == "predict" else {})}

    def launch(self, mode="collect"):
        with patch("kpl_insight.local_runtime.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "[]")), patch.object(self.control, "commands", self.safe_worker):
            return self.control.start(mode, "20260004")

    def test_start_logs_duplicate_guard_and_stop_only_owned_workers(self):
        state = self.launch()
        self.assertTrue(state["running"])
        self.assertEqual(set(state["processes"]), {"collector"})
        with self.assertRaisesRegex(ValueError, "先停止"):
            self.control.start("collect", "20260004")
        for _ in range(30):
            if "worker ready" in self.control.status()["logs"]["collector"]:
                break
            time.sleep(.1)
        self.assertIn("worker ready", self.control.status()["logs"]["collector"])
        process = self.control.children["collector"]
        state = self.control.stop()
        self.assertFalse(state["running"])
        self.assertIsNotNone(process.poll())

    def test_second_panel_cannot_start_duplicate_pipeline(self):
        self.launch()
        other = RuntimeControl(self.site, self.root)
        try:
            with patch("kpl_insight.local_runtime.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "[]")):
                with self.assertRaisesRegex(ValueError, "另一个"):
                    other.start("collect", "20260004")
        finally:
            other.stop()
        self.assertTrue(self.control.status()["running"])

    def test_missing_model_and_invalid_inputs_never_spawn(self):
        with patch("kpl_insight.local_runtime.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "未找到模型"):
                self.control.start("predict", "20260004")
            for mode, league in (("shell", "20260004"), ("collect", "1;echo hello"), ("collect", "０１"), ("collect", "0")):
                with self.assertRaises(ValueError):
                    self.control.start(mode, league)
            spawn.assert_not_called()

    def test_prediction_starts_both_workers_and_reports_partial_failure(self):
        model = self.root / "output/models/v9_official_platform.joblib"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"placeholder; not loaded by this test")
        state = self.launch("predict")
        self.assertTrue(state["model_found"])
        self.assertEqual(set(state["processes"]), {"collector", "exporter"})
        self.control.children["exporter"].terminate()
        self.control.children["exporter"].wait(timeout=5)
        state = self.control.status()
        self.assertFalse(state["running"])
        self.assertTrue(state["error"])

    def test_one_click_automatically_uses_next_event_and_collects_without_model(self):
        today = datetime.now(timezone(timedelta(hours=8))).date()
        assets = self.site / "assets"
        assets.mkdir()
        rows = [{"leagueId": "1", "date": (today - timedelta(days=1)).isoformat(), "st": 2},
                {"leagueId": "2", "date": (today + timedelta(days=1)).isoformat(), "st": 0},
                {"leagueId": "3", "date": (today + timedelta(days=30)).isoformat(), "st": 0}]
        (assets / "schedule_all.js").write_text("SCHEDULE = " + json.dumps(rows) + ";", encoding="utf-8")
        with patch("kpl_insight.local_runtime.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "[]")), patch.object(self.control, "commands", self.safe_worker):
            state = self.control.start()
        self.assertEqual(state["league"], "2")
        self.assertEqual(state["mode"], "collect")
        self.assertTrue(state["running"])

    def test_one_click_automatically_predicts_when_model_exists(self):
        model = self.root / "output/models/v9_official_platform.joblib"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"placeholder; never loaded")
        with patch.object(self.control, "default_league", return_value="20260004"), patch("kpl_insight.local_runtime.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "[]")), patch.object(self.control, "commands", self.safe_worker):
            state = self.control.start()
        self.assertEqual(state["mode"], "predict")
        self.assertEqual(set(state["processes"]), {"collector", "exporter"})


if __name__ == "__main__":
    unittest.main()
