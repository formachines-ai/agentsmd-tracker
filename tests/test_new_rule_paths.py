"""Offline, read-only (T-0199): .github/instructions/ and .claude/rules/ are tracked paths; first scan = baseline.

No network, no writes. Run: python3 -B -m unittest tests.test_new_rule_paths
"""
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402

NEW = (".github/instructions", ".claude/rules")
REPO = {"full_name": "o/n", "owner": "o", "name": "n", "language": "Python", "stars": 5000}


def snap(files):
    return {"status": "ok", "default_branch": "main", "files": files}


class NewRulePaths(unittest.TestCase):
    def test_registered_as_directories(self):
        kinds = {s["path"]: (s["kind"], s["label"]) for s in build.PATHS}
        self.assertEqual(kinds[".github/instructions"], ("dir", ".github/instructions/"))
        self.assertEqual(kinds[".claude/rules"], ("dir", ".claude/rules/"))
        self.assertIn(".github/instructions/", build.paths_text())
        self.assertIn(".claude/rules/", build.paths_text())

    def test_tracked_since_none_then_first_scan_date(self):
        base = {s["path"]: 1 for s in build.PATHS if s["path"] not in NEW}
        hist = [{"date": "2026-11-17", "counts": dict(base)}]
        ts = build.tracked_since(hist)
        for p in NEW:
            self.assertIsNone(ts[p])
        hist.append({"date": "2026-11-19", "counts": {**base, NEW[0]: 3, NEW[1]: 0}})
        ts = build.tracked_since(hist)
        for p in NEW:
            self.assertEqual(ts[p], "2026-11-19")
        self.assertEqual(ts["AGENTS.md"], "2026-11-17")

    def test_first_scan_of_new_path_is_not_added(self):
        old = {"AGENTS.md": {"present": True, "size": 10}}   # snapshot from before the paths existed
        new = {"AGENTS.md": {"present": True, "size": 10},
               NEW[0]: {"present": True, "size": None}, NEW[1]: {"present": True, "size": None}}
        added, removed = build.diff_snapshots(REPO, snap(old), snap(new))
        self.assertEqual(added, [])
        self.assertEqual(removed, [])

    def test_later_appearance_counts_as_added(self):
        prev = snap({NEW[0]: {"present": False, "size": None, "definite": True}})
        cur = snap({NEW[0]: {"present": True, "size": None}})
        added, _ = build.diff_snapshots(REPO, prev, cur)
        self.assertEqual([a["path"] for a in added], [NEW[0]])
        self.assertTrue(added[0]["url"].endswith("/tree/main/.github/instructions"))


if __name__ == "__main__":
    unittest.main()
