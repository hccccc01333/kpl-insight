"""Verify the default website starts independently of research dependencies."""
import json
from urllib.request import Request
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


class FrontendTests(unittest.TestCase):
    def test_source_launcher_serves_assets_and_limits_document_root(self):
        # An absolute launcher must also work outside the project directory.
        process = subprocess.Popen(
            [sys.executable, "-S", str(ROOT / "start.py"), "--port", "0", "--no-browser"],
            cwd=ROOT.parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            line = process.stdout.readline().strip()
            self.assertTrue(line.startswith("KPL Insight: http://127.0.0.1:"), line)
            url = line.split(": ", 1)[1]
            for route in ("", "schedule.html", "match.html", "assets/common.js", "assets/schedule_all.js"):
                with urlopen(url + route, timeout=10) as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.read())
            for route in ("pyproject.toml", ".git/config", "../pyproject.toml"):
                with self.assertRaises(HTTPError) as raised:
                    urlopen(url + route, timeout=10)
                self.assertEqual(raised.exception.code, 404)
                raised.exception.close()
            with urlopen(url + "__kpl_local__/status", timeout=10) as response:
                state = json.load(response)
                self.assertFalse(state["running"])
                token = state["token"]
            for headers in (
                {"X-KPL-Token": token, "Origin": "https://example.com"},
                {"X-KPL-Token": "wrong"},
                {"X-KPL-Token": token, "Host": "example.com"},
            ):
                request = Request(url + "__kpl_local__/stop", data=b"{}", headers=headers, method="POST")
                with self.assertRaises(HTTPError) as raised:
                    urlopen(request, timeout=10)
                self.assertEqual(raised.exception.code, 403)
                raised.exception.close()
            request = Request(url + "__kpl_local__/stop", data=b"{}", headers={"X-KPL-Token": token}, method="POST")
            with urlopen(request, timeout=10) as response:
                self.assertFalse(json.load(response)["running"])
        finally:
            process.terminate()
            process.communicate(timeout=10)

    def test_archive_and_analysis_share_bundled_default(self):
        from kpl_insight.web import DEFAULT_SITE_DIR
        from kpl_insight.analysis.loaders import DEFAULT_SITE_DIR as ANALYSIS_SITE_DIR

        self.assertEqual(DEFAULT_SITE_DIR, ANALYSIS_SITE_DIR)
        self.assertTrue((DEFAULT_SITE_DIR / "index.html").is_file())
        manifest = json.loads((DEFAULT_SITE_DIR / "bundle-manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            self.assertTrue((DEFAULT_SITE_DIR / entry["path"]).is_file(), entry["path"])


if __name__ == "__main__":
    unittest.main()
