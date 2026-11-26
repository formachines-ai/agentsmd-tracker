"""Offline (T-0253): a --no-scan build into a temp dir has every promised public address, the AI footer, and no 'no longer maintained' text."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent


class PublicComplete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="public-complete-"))
        shutil.copy(REPO / "build.py", cls.tmp / "build.py")
        shutil.copytree(REPO / "static", cls.tmp / "static")
        shutil.copytree(REPO / "data", cls.tmp / "data")
        (cls.tmp / "public").mkdir()
        subprocess.run(["chmod", "-R", "u+w", str(cls.tmp)], check=True)
        subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=cls.tmp, check=True, capture_output=True)
        cls.pub = cls.tmp / "public"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_files_exist(self):
        for f in ("index.html", "build.json", "stats.json", "today.json", "feed.xml", "llms.txt", "legal/index.html"):
            self.assertTrue((self.pub / f).is_file(), f)

    def test_repo_card(self):
        cards = list((self.pub / "repo").glob("*/*/index.html"))
        self.assertGreater(len(cards), 100)

    def test_index_footer_and_no_stub_text(self):
        h = (self.pub / "index.html").read_text()
        self.assertIn("Built by AI agents (agent-team)", h)
        self.assertNotIn("no longer maintained", h.lower())


if __name__ == "__main__":
    unittest.main()
