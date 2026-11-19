"""Offline (T-0212): M + excluded = sample size, excluded repos keep a card with status, the sample never shrinks.

Builds a temp copy of the repository with --no-scan; nothing is written to the checkout."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent


class SampleDenominator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="denom-"))
        shutil.copy(REPO / "build.py", cls.tmp / "build.py")
        shutil.copytree(REPO / "static", cls.tmp / "static")
        shutil.copytree(REPO / "data", cls.tmp / "data")
        (cls.tmp / "public").mkdir()
        subprocess.run(["chmod", "-R", "u+w", str(cls.tmp)], check=True)
        subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=cls.tmp, check=True, capture_output=True)
        cls.pub = cls.tmp / "public"
        cls.stats = json.loads((cls.pub / "stats.json").read_text())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_m_plus_excluded_is_sample(self):
        d = self.stats["denominator"]
        self.assertEqual(d["M"] + d["excluded"], d["sample_size"])
        self.assertEqual(d["sample_size"], self.stats["sample_size"])
        self.assertEqual(d["M"], self.stats["scanned"])
        self.assertEqual(sum(d["excluded_by_reason"].values()), d["excluded"])
        self.assertEqual(len(d["excluded_repos"]), d["excluded"])
        for key in ("moved", "deleted", "archived", "fork", "unreachable"):
            self.assertIn(key, d["excluded_by_reason"])
        self.assertRegex(d["date"], r"^\d{4}-\d\d-\d\d$")

    def test_existing_keys_kept(self):
        for k in ("sample", "sample_size", "scanned", "pending", "unreachable", "counts", "history"):
            self.assertIn(k, self.stats)

    def test_excluded_repo_has_card_with_status(self):
        items = self.stats["denominator"]["excluded_repos"]
        for it in items:
            owner, name = it["repo"].split("/")
            html = (self.pub / "repo" / owner / name / "index.html").read_text()
            self.assertIn(f"Status: {it['status']}", html)
            self.assertIn("First seen in the sample on", html)
            idx = json.loads((self.pub / "repo" / owner / name / "index.json").read_text())
            self.assertEqual(idx["status"], "unreachable")

    def test_llms_txt_defines_m(self):
        txt = (self.pub / "llms.txt").read_text()
        self.assertIn("Denominator: M =", txt)
        self.assertIn("excluded =", txt)

    def test_no_repo_leaves_the_sample(self):
        repos = {r["full_name"] for r in json.loads((REPO / "data" / "repos.json").read_text())["repos"]}
        hist = [json.loads(p.read_text()) for p in sorted((REPO / "data" / "history").glob("*.json"))]
        samples = [h["sample"] for h in hist]
        self.assertEqual(samples, sorted(samples), "sample shrank between snapshots")
        self.assertGreaterEqual(len(repos), samples[-1])
        for p in (REPO / "data" / "scan").glob("*.json"):
            self.assertIn(p.stem.replace("__", "/", 1), repos)


if __name__ == "__main__":
    unittest.main()
