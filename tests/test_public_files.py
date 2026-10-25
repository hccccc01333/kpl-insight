"""Publication checks must catch forced additions as well as normally ignored files."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publication_policy", ROOT / "tools/check_public_files.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublicationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = module.load_policy()

    def test_runtime_source_and_selected_usage_files_are_allowed(self):
        for path in ["README.md", "docs/getting-started.md", "kpl_insight/core.py", "kpl_insight/resources/knowledge.json", "kpl_insight/models/new_model.py", "tests/test_new_feature.py"]:
            with self.subTest(path=path):
                self.assertTrue(module.is_allowed(path, self.policy))

    def test_internal_documents_and_generated_assets_are_rejected(self):
        for path in ["docs/design/plan.md", "docs/internal-note.md", "planning.md", "reports/result.json", "promo/film.mp4", "data/realtime/schedule.csv", "docs/images/internal-notes.md"]:
            with self.subTest(path=path):
                self.assertFalse(module.is_allowed(path, self.policy))

    def test_private_material_cannot_hide_in_an_allowed_source_tree(self):
        for path in ["kpl_insight/.env", "kpl_insight/.secrets/token.py", "tests/output/private.py", "kpl_insight/__pycache__/core.py", "tests/../../README.md"]:
            with self.subTest(path=path):
                self.assertFalse(module.is_allowed(path, self.policy))


if __name__ == "__main__":
    unittest.main()
