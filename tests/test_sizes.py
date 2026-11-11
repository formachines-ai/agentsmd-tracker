"""Offline tests: card size wording and stats.json small_files on fixture scan records.

All module paths of build.py are pointed to a temp directory; no network, no writes to data/ or public/.
Run: python3 -m unittest discover -s tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sizes"


def _setup(tmp: Path):
    data = tmp / "data"
    (data / "scan").mkdir(parents=True)
    (data / "history").mkdir()
    repos = json.loads((FIXTURE / "repos.json").read_text())["repos"]
    for r in repos:
        (data / "scan" / f"{r['owner']}__{r['name']}.json").write_text(
            (FIXTURE / "scan" / f"{r['owner']}__{r['name']}.json").read_text())
    build.DATA_DIR, build.SCAN_DIR, build.HISTORY_DIR = data, data / "scan", data / "history"
    build.REPOS_FILE, build.GO_FILE = data / "repos.json", data / "go.json"
    build.PUBLIC_DIR = tmp / "public"
    return repos


class SizeFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved = {k: getattr(build, k) for k in ("DATA_DIR", "SCAN_DIR", "HISTORY_DIR", "REPOS_FILE", "GO_FILE", "PUBLIC_DIR")}
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        repos = _setup(tmp)
        cls.agg = build.aggregate(repos)
        stamp = "2026-11-11T04:00:00Z"
        info = {"site": build.SITE_BASE, "built_at": stamp, "data_delayed": False, "delay_reason": "", "scan": {}}
        today = {"date": "2026-11-11", "generated": stamp, "added": [], "removed": []}
        hist = [{"date": "2026-11-11", "generated": stamp, "scanned": len(cls.agg["ok"]),
                 "counts": cls.agg["counts"], "any": cls.agg["any"], "added": [], "removed": []}]
        build.render_site(repos, cls.agg, hist, today, info, build.sample_details(repos, repos, {}, cls.agg))
        cls.out = tmp / "public"

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._saved.items():
            setattr(build, k, v)
        cls._tmp.cleanup()

    def card(self, name):
        return (self.out / "repo" / "fx" / name / "index.html").read_text()

    def test_zero_bytes_card(self):
        self.assertIn("0 bytes (under 300 bytes)", self.card("zero"))

    def test_unknown_size_card(self):
        html = self.card("nolen")
        self.assertIn("size unknown", html)
        self.assertNotIn("under 300 bytes", html)

    def test_small_card(self):
        self.assertIn("120 bytes (under 300 bytes)", self.card("small"))

    def test_large_card_has_no_marker(self):
        html = self.card("large")
        self.assertIn("5,000 bytes", html)
        self.assertNotIn("under 300 bytes", html)
        self.assertNotIn("size unknown", html)

    def test_small_files_counts(self):
        sm = self.agg["small"]["AGENTS.md"]
        self.assertEqual(sm["zero_bytes"], 1)
        self.assertEqual(sm["unknown_size"], 1)
        self.assertEqual(sm["size_unknown"], 1)
        self.assertEqual(sm["count"], 2)          # 0 bytes + 120 bytes; unknown and 5000 are not counted
        self.assertEqual(sm["threshold_bytes"], 300)
        self.assertEqual(self.agg["sizes"]["AGENTS.md"]["count"], 3)   # known sizes only

    def test_stats_json_small_files(self):
        stats = json.loads((self.out / "stats.json").read_text())
        sf = stats["small_files"]
        self.assertEqual(sf["threshold_bytes"], 300)
        self.assertIsInstance(sf["date"], str)
        a = sf["AGENTS.md"]
        for k in ("count", "threshold_bytes", "zero_bytes", "unknown_size", "size_unknown"):
            self.assertIsInstance(a[k], int, k)
        self.assertEqual((a["count"], a["zero_bytes"], a["unknown_size"]), (2, 1, 1))

    def test_index_json_field_types(self):
        d = json.loads((self.out / "repo" / "fx" / "nolen" / "index.json").read_text())
        f = d["files"]["AGENTS.md"]
        self.assertIs(f["present"], True)
        self.assertIsNone(f["size"])
        self.assertIsInstance(f["url"], str)
        z = json.loads((self.out / "repo" / "fx" / "zero" / "index.json").read_text())["files"]["AGENTS.md"]
        self.assertEqual(z["size"], 0)
        self.assertIsInstance(z["size"], int)
        self.assertIsInstance(d["stars"], int)
        self.assertIsInstance(d["status"], str)


if __name__ == "__main__":
    unittest.main()
