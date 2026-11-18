"""Offline, read-only (T-0203): a path with tracked_since null is "Not measured yet", never 0 of N / 0.0 %.

Builds one tiny fixture in a temp copy, in two states: (1) the two newest paths have no first scan, (2) they do.
Run: python3 -B -m unittest tests.test_unmeasured_paths
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import build  # noqa: E402

NEW = (".github/instructions", ".claude/rules")
SCAN = "2026-11-18T05:30:07Z"


def run_build(with_new):
    t = Path(tempfile.mkdtemp(prefix="unmeasured-"))
    shutil.copy(REPO / "build.py", t / "build.py")
    shutil.copytree(REPO / "static", t / "static")
    subprocess.run(["chmod", "-R", "u+w", str(t)], check=True)
    for d in ("data/scan", "data/history", "public"):
        (t / d).mkdir(parents=True)
    (t / "data" / "repos.json").write_text(json.dumps({"generated": SCAN, "query": {}, "repos": [
        {"id": 1, "full_name": "o/a", "owner": "o", "name": "a", "language": "Python", "stars": 9, "default_branch": "main"}]}))
    (t / "data" / "scan" / "o__a.json").write_text(json.dumps({"checked": SCAN, "status": "ok", "default_branch": "main",
                                                               "files": {"AGENTS.md": {"present": True, "size": 10},
                                                                         **({NEW[1]: {"present": True, "size": None}} if with_new else {})}}))
    base = {s["path"]: 0 for s in build.PATHS if s["path"] not in NEW}
    base["AGENTS.md"] = 1
    counts = {**base, **({NEW[0]: 0, NEW[1]: 1} if with_new else {})}
    lang = {"repos": 1, **counts}
    (t / "data" / "history" / "2026-11-18.json").write_text(json.dumps({
        "date": "2026-11-18", "generated": SCAN, "sample": 1, "scanned": 1, "total": 1, "counts": counts, "any": 1,
        "by_language": {"Python": lang}, "added": [], "removed": []}))
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "BUILD_NOW")}
    r = subprocess.run([sys.executable, "-B", "build.py", "--no-scan", "--now", "2026-11-18T06:00:00Z"], cwd=t,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr[-800:]
    return t / "public"


class UnmeasuredPaths(unittest.TestCase):
    def test_unmeasured_state(self):
        pub = run_build(False)
        stats = json.loads((pub / "stats.json").read_text())
        for p in NEW:
            self.assertIs(stats["measured"][p], False)
            self.assertIsNone(stats["counts"][p])
            self.assertIsNone(stats["shares"][p])
            self.assertIsNone(stats["by_language"]["Python"][p])
            self.assertIsNone(stats["tracked_since"][p])
        self.assertIs(stats["measured"]["AGENTS.md"], True)
        self.assertEqual(stats["counts"]["AGENTS.md"], 1)
        self.assertEqual(stats["shares"]["AGENTS.md"], 100.0)
        self.assertEqual(set(stats["measured"]), set(stats["counts"]))
        home = (pub / "index.html").read_text()
        for page in (home, (pub / "lang" / "python" / "index.html").read_text()):
            self.assertIn("Not measured yet", page)
        self.assertIn("Not measured yet: no first scan recorded", home)
        for label in (".github/instructions/", ".claude/rules/"):
            m = re.search(r'<section class="card">\s*<h2><code>' + re.escape(label) + r'</code></h2>(.*?)</section>', home, re.S)
            self.assertIn("Not measured yet", m.group(1))
            self.assertNotIn(" of ", m.group(1))
            self.assertNotIn("%", m.group(1))
        self.assertIn("null", (pub / "llms.txt").read_text())
        self.assertIn("measured:false", (pub / "llms.txt").read_text())

    def test_measured_state(self):
        pub = run_build(True)
        stats = json.loads((pub / "stats.json").read_text())
        for p in NEW:
            self.assertIs(stats["measured"][p], True)
            self.assertEqual(stats["tracked_since"][p], "2026-11-18")
        self.assertEqual(stats["counts"][NEW[0]], 0)
        self.assertEqual(stats["counts"][NEW[1]], 1)
        self.assertEqual(stats["shares"][NEW[1]], 100.0)
        home = (pub / "index.html").read_text()
        self.assertNotIn("Not measured yet", home)
        m = re.search(r'<h2><code>\.claude/rules/</code></h2>(.*?)</section>', home, re.S)
        self.assertIn("1 <span", m.group(1))
        self.assertIn("Measured since 2026-11-18", m.group(1))
        self.assertIn("1 repos checked", m.group(1))
        self.assertNotIn("Not measured yet", (pub / "lang" / "python" / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
