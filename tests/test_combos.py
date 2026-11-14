"""Offline, read-only: stats.json 'combos' equals a recount from the committed per-repo index.json files.

Run: python3 -B -m unittest tests.test_combos
"""
import json
import re
import unittest
from pathlib import Path

PUB = Path(__file__).resolve().parent.parent / "public"
KEYS = ("both_agents_claude", "agents_only", "claude_only", "neither")


def recount():
    c = dict.fromkeys(KEYS, 0)
    for f in sorted((PUB / "repo").glob("*/*/index.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("status") != "ok":
            continue   # unreachable / pending repos are outside the scanned denominator
        files = d["files"]
        pa = bool(files["AGENTS.md"]["present"])
        pc = bool(files["CLAUDE.md"]["present"])
        c["both_agents_claude" if pa and pc else "agents_only" if pa else "claude_only" if pc else "neither"] += 1
    return c


class Combos(unittest.TestCase):
    def setUp(self):
        self.stats = json.loads((PUB / "stats.json").read_text(encoding="utf-8"))
        self.cb = self.stats["combos"]

    def test_sum_equals_scanned_sample(self):
        for k in KEYS:
            self.assertIsInstance(self.cb[k], int)
        self.assertEqual(sum(self.cb[k] for k in KEYS), self.stats["scanned"])

    def test_recount_from_repo_index(self):
        self.assertEqual({k: self.cb[k] for k in KEYS}, recount())

    def test_home_line(self):
        html = (PUB / "index.html").read_text(encoding="utf-8")
        m = re.search(r'<p id="combos-line">(.*?)</p>', html, re.S)
        self.assertIsNotNone(m)
        t = m.group(1)
        self.assertIn(self.stats["generated"][:10], t)
        nums = [int(x.replace(",", "")) for x in re.findall(r"([\d,]+) (?:have both|AGENTS\.md only|CLAUDE\.md only|neither)", t)]
        self.assertEqual(nums, [self.cb[k] for k in KEYS])


if __name__ == "__main__":
    unittest.main()
