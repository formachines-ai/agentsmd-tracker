"""Offline, read-only (T-0209): per-path checked/unknown. A repo whose snapshot predates a path's tracked_since is
'unknown' for it, never an absence. Builds fixtures in a temp copy: partial coverage and full coverage.
Run: python3 -B -m unittest tests.test_per_path_coverage"""
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

NEW = ".github/instructions"
OLD_DAY, NEW_DAY = "2026-11-18", "2026-11-19"


def run_build(old_snapshot_for_b):
    """Repos a (fresh 19.11, present), b (snapshot 18.11 if old_snapshot_for_b else 19.11), c (fresh, absent)."""
    t = Path(tempfile.mkdtemp(prefix="pathcov-"))
    shutil.copy(REPO / "build.py", t / "build.py")
    shutil.copytree(REPO / "static", t / "static")
    subprocess.run(["chmod", "-R", "u+w", str(t)], check=True)
    for d in ("data/scan", "data/history", "public"):
        (t / d).mkdir(parents=True)
    names = ["a", "b", "c"]
    (t / "data" / "repos.json").write_text(json.dumps({"generated": NEW_DAY + "T05:00:00Z", "query": {}, "repos": [
        {"id": i, "full_name": f"o/{n}", "owner": "o", "name": n, "language": "Python", "stars": 9, "default_branch": "main"}
        for i, n in enumerate(names, 1)]}))
    old_paths = [s["path"] for s in build.PATHS if s["path"] != NEW and not s["path"].endswith("rules") or s["path"] == ".cursor/rules"]
    old_paths = [p for p in old_paths if p not in (NEW, ".claude/rules")]

    def scan(day, with_new, present):
        files = {p: {"present": p == "AGENTS.md", "size": 5 if p == "AGENTS.md" else None} for p in old_paths}
        if with_new:
            files[NEW] = {"present": present, "size": None}
        return {"checked": day + "T05:00:00Z", "status": "ok", "default_branch": "main", "files": files}
    sc = {"a": scan(NEW_DAY, True, True), "b": scan(OLD_DAY if old_snapshot_for_b else NEW_DAY, not old_snapshot_for_b, False),
          "c": scan(NEW_DAY, True, False)}
    for n, v in sc.items():
        (t / "data" / "scan" / f"o__{n}.json").write_text(json.dumps(v))
    base = {p: 0 for p in old_paths}
    base["AGENTS.md"] = 3
    (t / "data" / "history" / f"{OLD_DAY}.json").write_text(json.dumps({
        "date": OLD_DAY, "generated": OLD_DAY + "T05:00:00Z", "sample": 3, "scanned": 3, "total": 3, "counts": base, "any": 3,
        "by_language": {"Python": {"repos": 3, "any": 3, **base}}, "added": [], "removed": []}))
    cn = {**base, NEW: 1}
    (t / "data" / "history" / f"{NEW_DAY}.json").write_text(json.dumps({
        "date": NEW_DAY, "generated": NEW_DAY + "T05:00:00Z", "sample": 3, "scanned": 3, "total": 3, "counts": cn, "any": 3,
        "by_language": {"Python": {"repos": 3, "any": 3, **cn}}, "added": [], "removed": []}))
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "BUILD_NOW")}
    r = subprocess.run([sys.executable, "-B", "build.py", "--no-scan", "--now", NEW_DAY + "T06:00:00Z"], cwd=t,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr[-800:]
    return t / "public"


class PerPathCoverage(unittest.TestCase):
    def test_partial_coverage(self):
        pub = run_build(True)
        st = json.loads((pub / "stats.json").read_text())
        # tracked_since for the new path is 19.11 (first history day holding it); b's snapshot is 18.11
        self.assertEqual(st["tracked_since"][NEW], NEW_DAY)
        self.assertEqual((st["checked"][NEW], st["unknown"][NEW]), (2, 1))
        self.assertEqual(st["checked"][NEW] + st["unknown"][NEW], st["scanned"])
        self.assertEqual(st["counts"][NEW], 1)
        self.assertEqual(st["shares"][NEW], 50.0)   # 1 / 2 checked, not 1 / 3
        self.assertEqual((st["checked"]["AGENTS.md"], st["unknown"]["AGENTS.md"]), (3, 0))
        self.assertEqual(st["shares"]["AGENTS.md"], 100.0)
        for page in ("index.html", "lang/python/index.html"):
            html = (pub / page).read_text()
            self.assertIn("1 of 2 checked (50.0 %) · 1 not yet checked · since 2026-11-19", html)
        self.assertIn("not yet checked</td>", (pub / "lang/python/index.html").read_text())
        cj = lambda n: json.loads((pub / "repo" / "o" / n / "index.json").read_text())
        self.assertIsNone(cj("b")["files"][NEW]["present"])
        self.assertIs(cj("a")["files"][NEW]["present"], True)
        self.assertIs(cj("c")["files"][NEW]["present"], False)
        self.assertIs(cj("b")["files"]["AGENTS.md"]["present"], True)
        llms = (pub / "llms.txt").read_text()
        self.assertIn("checked", llms)
        self.assertIn("unknown", llms)

    def test_full_coverage(self):
        pub = run_build(False)
        st = json.loads((pub / "stats.json").read_text())
        self.assertEqual((st["checked"][NEW], st["unknown"][NEW]), (3, 0))
        self.assertEqual(st["shares"][NEW], round(100 / 3, 1))
        html = (pub / "index.html").read_text()
        self.assertNotIn("not yet checked ·", html.replace("not yet checked</td>", ""))
        self.assertNotIn("Partly checked paths", (pub / "lang/python/index.html").read_text())
        self.assertIs(json.loads((pub / "repo/o/b/index.json").read_text())["files"][NEW]["present"], False)


if __name__ == "__main__":
    unittest.main()
