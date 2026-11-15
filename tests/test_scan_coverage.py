"""Offline: scan coverage (fresh / carried_over / partial / stopped) in build.json, index.html and llms.txt.
Builds with `build.py --no-scan` in a temp copy from fixture scan data of a stopped run. No network, no writes to the checkout."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DAY, OLD = "2026-11-15", "2026-11-13"


def snap(day, status="ok"):
    return {"checked": day + "T05:00:00Z", "status": status, "default_branch": "main",
            "files": {"AGENTS.md": {"present": True, "size": 10}}}


class ScanCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="coverage-"))
        t = cls.tmp
        shutil.copy(REPO / "build.py", t / "build.py")
        shutil.copytree(REPO / "static", t / "static")
        subprocess.run(["chmod", "-R", "u+w", str(t)], check=True)   # the checkout may be read-only
        (t / "data" / "scan").mkdir(parents=True, exist_ok=True)
        (t / "data" / "history").mkdir()
        (t / "public").mkdir()
        repos = []
        # 3 fresh, 2 carried over (oldest 2026-11-13), 1 unreachable
        plan = [("a", DAY), ("b", DAY), ("c", DAY), ("d", "2026-11-14"), ("e", OLD), ("f", None)]
        for n, day in plan:
            repos.append({"id": 1, "full_name": f"o/{n}", "owner": "o", "name": n, "language": "Python", "stars": 9,
                          "default_branch": "main"})
            doc = snap(DAY, "unreachable") if day is None else snap(day)
            (t / "data" / "scan" / f"o__{n}.json").write_text(json.dumps(doc))
        (t / "data" / "repos.json").write_text(json.dumps({"generated": DAY + "T05:00:00Z", "query": {}, "repos": repos}))
        (t / "data" / "history" / f"{DAY}.json").write_text(json.dumps(
            {"date": DAY, "generated": DAY + "T05:30:00Z", "total": 5, "counts": {}, "any": 5, "by_language": {}, "added": [], "removed": []}))
        (t / "public" / "build.json").write_text(json.dumps({"scan": {
            "scanned": 4, "ok": 3, "unreachable": 1, "error": 0, "partial": 1, "rate_limited": False, "stopped": True,
            "added": 0, "removed": 0, "generated": DAY + "T05:30:00Z"}}))
        r = subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=t, capture_output=True, text=True)
        cls.rc, cls.log = r.returncode, r.stderr + r.stdout
        pub = t / "public"
        cls.build = json.loads((pub / "build.json").read_text()) if (pub / "build.json").exists() else {}
        cls.index = (pub / "index.html").read_text() if (pub / "index.html").exists() else ""
        cls.llms = (pub / "llms.txt").read_text() if (pub / "llms.txt").exists() else ""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_build_ok(self):
        self.assertEqual(self.rc, 0, self.log[-800:])

    def test_sums(self):
        s = self.build["scan"]
        for k in ("fresh", "carried_over", "partial"):
            self.assertIsInstance(s[k], int, k)
        self.assertEqual((s["fresh"], s["carried_over"], s["partial"]), (3, 2, 1))
        self.assertEqual(s["fresh"] + s["carried_over"], self.build["scanned_ok"])
        self.assertIs(s["stopped"], True)
        self.assertEqual(s["scanned"], 4)  # old keys keep their values
        self.assertIn("stopped", s["stopped_meaning"])
        self.assertEqual(s["carried_over_oldest"], OLD)

    def test_home_line(self):
        m = re.search(r'id="scan-coverage">([^<]*)', self.index)
        self.assertTrue(m)
        self.assertIn(f"3 repos checked on {DAY}, 2 carried over from earlier scans (oldest {OLD})", m.group(1))

    def test_llms(self):
        line = next(x for x in self.llms.splitlines() if x.startswith("Scan coverage"))
        for w in ("fresh", "carried_over", "partial", "stopped"):
            self.assertIn(w, line)
        self.assertIn("3 fresh", line)

    def test_published(self):
        b = json.loads((REPO / "public" / "build.json").read_text())["scan"]
        self.assertEqual(b["fresh"] + b["carried_over"], json.loads((REPO / "public" / "build.json").read_text())["scanned_ok"])
        readme = (REPO / "README.md").read_text()
        for w in ("fresh", "carried_over", "partial", "stopped"):
            self.assertIn(w, readme)


if __name__ == "__main__":
    unittest.main()
