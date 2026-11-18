"""Offline, read-only (T-0200): numbers the README states agree with build.PATHS and the build.py constants."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import build  # noqa: E402

README = (REPO / "README.md").read_text()


class ReadmeFacts(unittest.TestCase):
    def test_path_count(self):
        n = len(build.PATHS)
        m = re.search(r"\((\d+) paths today\)", README)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), n)
        m = re.search(r"Requests per repo: \*\*(\d+)\*\*[^:]*: (\d+) path HEADs", README)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), build.REQ_PER_REPO)
        self.assertEqual(int(m.group(2)), n)
        self.assertIn(f"only when all {n} paths are absent", README.replace("\n  ", " "))
        self.assertIn(f"otherwise the repo makes {n + 1}", README.replace("\n  ", " "))
        for p in build.PATHS:
            self.assertIn(f"`{p['path']}`", README)

    def test_scan_time_formula(self):
        repos = len(json.loads((REPO / "data" / "repos.json").read_text())["repos"])
        m = re.search(r"`PAUSE_S` = ([\d.]+) s.*?(\d+) requests × ([\d ]+) repos × ([\d.]+) s = ([\d ]+(?:\.\d+)?) s ≈ (\d+) min",
                      README, re.S)
        self.assertIsNotNone(m)
        pause, req, rp, pause2, total, minutes = m.groups()
        rp = int(rp.replace(" ", ""))
        self.assertEqual(float(pause), build.PAUSE_S)
        self.assertEqual(float(pause2), build.PAUSE_S)
        self.assertEqual(int(req), build.REQ_PER_REPO)
        self.assertEqual(rp, repos)
        secs = build.REQ_PER_REPO * repos * build.PAUSE_S
        self.assertAlmostEqual(float(total.replace(" ", "")), secs, places=1)
        self.assertEqual(int(minutes), round(secs / 60))

    def test_test_file_count_not_stale(self):
        n = len(list((REPO / "tests").glob("test_*.py")))
        for m in re.finditer(r"\b(\d+)\s+(?:test\s+)?files?\b", README):
            self.assertEqual(int(m.group(1)), n, m.group(0))
        for m in re.finditer(r"tests/test_\*\.py[^\n]{0,40}?\((\d+)", README):
            self.assertEqual(int(m.group(1)), n, m.group(0))


if __name__ == "__main__":
    unittest.main()
