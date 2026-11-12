"""Offline, read-only: stats.json combinations add up to the sample size and the home page shows the same numbers.

Reads only the committed public/ files; writes nothing. Run: python3 -m unittest tests.test_combinations
"""
import json
import re
import unittest
from pathlib import Path

PUB = Path(__file__).resolve().parent.parent / "public"
KEYS = ("agents_only", "claude_only", "both", "neither", "agents_and_copilot")


class Combinations(unittest.TestCase):
    def setUp(self):
        self.stats = json.loads((PUB / "stats.json").read_text(encoding="utf-8"))
        self.cb = self.stats["combinations"]
        html = (PUB / "index.html").read_text(encoding="utf-8")
        m = re.search(r'<section id="combinations">(.*?)</section>', html, re.S)
        self.assertIsNotNone(m, "combinations block missing on /")
        self.block = m.group(1)

    def test_sum_equals_sample(self):
        for k in KEYS:
            self.assertIsInstance(self.cb[k], int)
        self.assertEqual(sum(self.cb[k] for k in KEYS[:4]), self.stats["sample_size"])
        self.assertEqual(self.cb["total"], self.stats["sample_size"])

    def test_date_is_generated_date(self):
        self.assertEqual(self.cb["date"], self.stats["generated"][:10])
        self.assertIn(self.cb["date"], self.block)

    def test_home_numbers_equal_stats(self):
        rows = re.findall(r"<tr><th scope=\"row\">.*?</th><td>([\d,]+)</td>", self.block)
        self.assertEqual([int(x.replace(",", "")) for x in rows], [self.cb[k] for k in KEYS])
        self.assertIn('href="/stats.json"', self.block)


if __name__ == "__main__":
    unittest.main()
