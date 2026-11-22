"""Offline, read-only (T-0230): .clinerules, .windsurf/rules and .agents are tracked paths; before the first scan
tracked_since is null and cards say "not measured yet (not yet scanned)", never a bare 0 / absent.

Run: python3 -B -m unittest tests.test_new_paths
"""
import json
import os
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

NEW = (".clinerules", ".windsurf/rules", ".agents")
SCAN = "2026-11-18T05:30:07Z"


def run_build(with_new):
    t = Path(tempfile.mkdtemp(prefix="newpaths-"))
    shutil.copy(REPO / "build.py", t / "build.py")
    shutil.copytree(REPO / "static", t / "static")
    subprocess.run(["chmod", "-R", "u+w", str(t)], check=True)
    for d in ("data/scan", "data/history", "public"):
        (t / d).mkdir(parents=True)
    (t / "data" / "repos.json").write_text(json.dumps({"generated": SCAN, "query": {}, "repos": [
        {"id": 1, "full_name": "o/a", "owner": "o", "name": "a", "language": "Python", "stars": 9, "default_branch": "main"}]}))
    files = {"AGENTS.md": {"present": True, "size": 10}}
    if with_new:
        files.update({NEW[0]: {"present": True, "size": 5}, NEW[1]: {"present": False, "size": None}, NEW[2]: {"present": False, "size": None}})
    (t / "data" / "scan" / "o__a.json").write_text(json.dumps({"checked": SCAN, "status": "ok", "default_branch": "main", "files": files}))
    counts = {s["path"]: 0 for s in build.PATHS if with_new or s["path"] not in NEW}
    counts["AGENTS.md"] = 1
    if with_new:
        counts[NEW[0]] = 1
    (t / "data" / "history" / "2026-11-18.json").write_text(json.dumps({
        "date": "2026-11-18", "generated": SCAN, "sample": 1, "scanned": 1, "total": 1, "counts": counts, "any": 1,
        "by_language": {"Python": {"repos": 1, **counts}}, "added": [], "removed": []}))
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "BUILD_NOW")}
    r = subprocess.run([sys.executable, "-B", "build.py", "--no-scan", "--now", "2026-11-18T06:00:00Z"], cwd=t,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr[-800:]
    return t / "public"


class NewPaths(unittest.TestCase):
    def test_paths_entries(self):
        by = {s["path"]: s for s in build.PATHS}
        self.assertEqual(by[".clinerules"]["kind"], "file")
        self.assertEqual(by[".windsurf/rules"]["kind"], "dir")
        self.assertEqual(by[".agents"]["kind"], "dir")
        self.assertEqual(len(build.PATHS), len({s["path"] for s in build.PATHS}))

    def test_before_first_scan(self):
        pub = run_build(False)
        stats = json.loads((pub / "stats.json").read_text())
        card = json.loads((pub / "repo" / "o" / "a" / "index.json").read_text())
        html = (pub / "repo" / "o" / "a" / "index.html").read_text()
        for p in NEW:
            self.assertIn(p, stats["tracked_since"])
            self.assertIsNone(stats["tracked_since"][p])
            self.assertIsNone(stats["counts"][p])
            self.assertIsNone(card["files"][p]["present"])
            self.assertIs(card["files"][p]["measured"], False)
            self.assertIn(p, html)
        self.assertEqual(html.count("not yet scanned"), 3)
        self.assertIn("not yet scanned", html)

    def test_after_first_scan(self):
        pub = run_build(True)
        stats = json.loads((pub / "stats.json").read_text())
        card = json.loads((pub / "repo" / "o" / "a" / "index.json").read_text())
        for p in NEW:
            self.assertEqual(stats["tracked_since"][p], "2026-11-18")
        self.assertIs(card["files"][NEW[0]]["present"], True)
        self.assertIs(card["files"][NEW[1]]["present"], False)
        self.assertNotIn("not yet scanned", (pub / "repo" / "o" / "a" / "index.html").read_text())

    def test_history_not_zero_before_tracking(self):
        pub = run_build(False)
        home = (pub / "index.html").read_text()
        self.assertNotIn("<td>0</td><td>0</td><td>0</td></tr>", home.replace("\n", ""))


if __name__ == "__main__":
    unittest.main()
