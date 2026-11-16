"""Offline, read-only (T-0182): tracked_since from history fixtures. Run: python3 -B -m unittest tests.test_tracked_since"""
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402


class TrackedSince(unittest.TestCase):
    def test_first_scan_dates(self):
        base = {s["path"]: 1 for s in build.PATHS if not s["path"].endswith("AI_POLICY.md")}
        hist = [{"date": "2026-11-02", "counts": dict(base)}, {"date": "2026-11-03", "counts": dict(base)},
                {"date": "2026-11-04", "counts": {**base, "AI_POLICY.md": 25, ".github/AI_POLICY.md": 1}}]
        ts = build.tracked_since(hist)
        self.assertEqual(set(ts), {s["path"] for s in build.PATHS})
        self.assertEqual(ts["AGENTS.md"], "2026-11-02")
        self.assertEqual(ts["AI_POLICY.md"], "2026-11-04")
        self.assertEqual(ts[".github/AI_POLICY.md"], "2026-11-04")

    def test_never_scanned_is_none(self):
        self.assertIsNone(build.tracked_since([])["AGENTS.md"])


if __name__ == "__main__":
    unittest.main()
