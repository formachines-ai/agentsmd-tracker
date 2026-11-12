"""Offline, read-only test: stats.json small_files against the committed scan, and the home line against stats.json.
Reads data/scan/ and public/ only; writes nothing. Run: python3 -m unittest tests.test_small_files
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 300


def scan_counts(name):
    total = small = 0
    for f in sorted((ROOT / "data" / "scan").glob("*.json")):
        d = json.loads(f.read_text())
        if d.get("status") != "ok":
            continue
        e = d.get("files", {}).get(name, {})
        if e.get("present"):
            total += 1
            if isinstance(e.get("size"), int) and e["size"] < LIMIT:
                small += 1
    return small, total


class SmallFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stats = json.loads((ROOT / "public" / "stats.json").read_text())
        cls.sf = cls.stats["small_files"]

    def test_fields(self):
        self.assertEqual(self.sf["threshold_bytes"], LIMIT)
        self.assertEqual(self.sf["date"], self.stats["generated"][:10])
        self.assertEqual(self.sf["agents_md_total"], self.stats["counts"]["AGENTS.md"])
        self.assertEqual(self.sf["claude_md_total"], self.stats["counts"]["CLAUDE.md"])

    def test_counts_match_scan(self):
        self.assertEqual((self.sf["agents_md_under_300"], self.sf["agents_md_total"]), scan_counts("AGENTS.md"))
        self.assertEqual((self.sf["claude_md_under_300"], self.sf["claude_md_total"]), scan_counts("CLAUDE.md"))

    def test_home_matches_stats(self):
        html = (ROOT / "public" / "index.html").read_text()
        m = re.search(r'<p class="asof" id="small-files">(.*?)</p>', html, re.S)
        self.assertIsNotNone(m)
        t = m.group(1)
        sf = self.sf
        self.assertIn(f"under {LIMIT} bytes on {sf['date']}", t)
        self.assertIn(f"AGENTS.md {sf['agents_md_under_300']:,} of {sf['agents_md_total']:,}", t)
        self.assertIn(f"CLAUDE.md {sf['claude_md_under_300']:,} of {sf['claude_md_total']:,}", t)
        self.assertIn('href="/stats.json"', t)
        self.assertGreater(html.index('id="small-files"'), html.index('id="combinations"'))


if __name__ == "__main__":
    unittest.main()
