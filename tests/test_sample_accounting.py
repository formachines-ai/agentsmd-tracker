"""Offline (T-0244): homepage note on the denominator equals stats.json denominator; M + excluded = total; cards keep status."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent


class SampleAccounting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="acct-"))
        shutil.copy(REPO / "build.py", cls.tmp / "build.py")
        shutil.copytree(REPO / "static", cls.tmp / "static")
        shutil.copytree(REPO / "data", cls.tmp / "data")
        (cls.tmp / "public").mkdir()
        subprocess.run(["chmod", "-R", "u+w", str(cls.tmp)], check=True)
        subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=cls.tmp, check=True, capture_output=True)
        cls.pub = cls.tmp / "public"
        cls.stats = json.loads((cls.pub / "stats.json").read_text())
        cls.html = (cls.pub / "index.html").read_text()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_totals(self):
        d = self.stats["denominator"]
        self.assertEqual(d["M"] + d["excluded"], d["total"])
        self.assertEqual(sum(d["excluded_by_reason"].values()), d["excluded"])
        for v in d["excluded_by_reason"].values():
            self.assertIsInstance(v, int)
        self.assertEqual(d["M"], self.stats["scanned"])

    def test_excluded_cards(self):
        for it in self.stats["denominator"]["excluded_repos"]:
            o, n = it["repo"].split("/")
            self.assertIn(f"Status: {it['status']}", (self.pub / "repo" / o / n / "index.html").read_text())

    def test_note_equals_stats(self):
        d = self.stats["denominator"]
        m = re.search(r'<p class="asof" id="sample-accounting">(.*?)</p>', self.html, re.S)
        self.assertIsNotNone(m)
        t = m.group(1)
        self.assertIn(d["date"], t)
        self.assertIn(f"M = {d['M']:,}", t)
        self.assertIn(f"{d['excluded']:,} of the {d['total']:,} sampled", t)
        for k, n in d["excluded_by_reason"].items():
            if n:
                self.assertIn(f"{n:,} {k}", t)
        self.assertNotIn("<script", t)


if __name__ == "__main__":
    unittest.main()
