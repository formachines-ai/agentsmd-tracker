"""Offline test: claude_agents_changes (fixtures) and its home line / llms.txt / stats.json consistency.
Reads build.py and public/ only. Run: python3 -m unittest tests.test_transitions"""
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build", ROOT / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def ev(name, path):
    return {"full_name": name, "path": path}


HISTORY = [
    {"date": "2026-11-02", "added": [], "removed": []},
    {"date": "2026-11-05", "added": [], "removed": [ev("o/removal", "CLAUDE.md")]},
    {"date": "2026-11-06", "added": [ev("o/addition", "AGENTS.md")], "removed": []},
]
NOW = {
    "o/removal": {"AGENTS.md"},                 # CLAUDE.md removed, AGENTS.md kept
    "o/addition": {"AGENTS.md", "CLAUDE.md"},   # AGENTS.md added, CLAUDE.md kept
    "o/nochange": {"AGENTS.md", "CLAUDE.md"},   # no events
    "o/plain": {"AGENTS.md"},                   # never had CLAUDE.md
    "o/today": {"AGENTS.md"},                   # first seen today: baseline, no events
    "o/both_gone": set(),                       # CLAUDE.md removed but AGENTS.md absent
}


class TransitionsTest(unittest.TestCase):
    def test_fixtures(self):
        h = HISTORY + [{"date": "2026-11-07", "added": [], "removed": [ev("o/both_gone", "CLAUDE.md")]}]
        r = build.claude_agents_changes(h, NOW, "2026-11-13T05:00:00Z")
        self.assertEqual(r["since"], "2026-11-02")
        self.assertEqual(r["date"], "2026-11-13")
        self.assertEqual(r["repos_claude_removed_agents_kept"], ["o/removal"])
        self.assertEqual(r["claude_removed_agents_kept"], 1)
        self.assertEqual(r["agents_added_claude_kept"], 1)

    def test_published(self):
        d = json.loads((ROOT / "public" / "stats.json").read_text())
        c = d["claude_agents_changes"]
        self.assertEqual(c["date"], d["generated"][:10])
        self.assertEqual(c["claude_removed_agents_kept"], len(c["repos_claude_removed_agents_kept"]))
        page = (ROOT / "public" / "index.html").read_text()
        m = re.search(r'<p class="asof" id="claude-agents-changes">(.*?)</p>', page)
        self.assertTrue(m)
        text = re.sub(r"<[^>]+>", "", m.group(1))
        self.assertLessEqual(len(text.split()), 40)
        self.assertIn(f'{c["claude_removed_agents_kept"]:,} repos', text)
        self.assertIn(f'{c["agents_added_claude_kept"]:,} added', text)
        self.assertIn('href="/stats.json"', m.group(1))
        self.assertIn("claude_agents_changes", (ROOT / "public" / "llms.txt").read_text())


if __name__ == "__main__":
    unittest.main()
