"""Offline, read-only (T-0174): repo card meta description and facts line agree with the card's index.json.

Walks public/repo/**/index.html. Run: python3 -B -m unittest tests.test_card_description
"""
import html
import json
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT / "public" / "repo"
DESC = re.compile(r'<meta name="description" content="([^"]*)"')
FACTS = re.compile(r'<p class="facts">(.*?)</p>', re.S)


class CardDescription(unittest.TestCase):
    def test_cards(self):
        pages = sorted(REPO.glob("*/*/index.html"))
        self.assertGreater(len(pages), 1000)
        bad = []
        for page in pages:
            data = json.loads(page.with_name("index.json").read_text())
            files = data["files"]
            txt = page.read_text()
            desc = html.unescape(DESC.search(txt).group(1))
            facts = re.sub(r"<[^>]+>", "", html.unescape(FACTS.search(txt).group(1)))
            name = str(page.relative_to(REPO).parent)
            none_ = [p for p, f in files.items() if f["present"] is None]
            if not 50 <= len(desc) <= 160:
                bad.append((name, "length", len(desc)))
            if len(none_) < len(files):
                if "tracked files not checked yet" in desc:
                    bad.append((name, "all-unchecked wording"))
                for p in ("AGENTS.md", "CLAUDE.md"):
                    f = files[p]["present"]
                    if f is not None and none_ and f"{p} {'yes' if f else 'no'}" not in desc:
                        bad.append((name, "status", p))
                    if f is True and p not in desc:
                        bad.append((name, "present missing", p))
            for src, label in ((desc, "desc"), (facts, "facts")):
                m = re.search(r"((?:[\w.\-/]+, )*[\w.\-/]+) not checked yet\.", src)
                said = set(m.group(1).split(", ")) if m else set()
                if len(none_) < len(files) and said != set(none_):
                    bad.append((name, label, "unchecked mismatch", sorted(said), none_))
        print(f"cards checked: {len(pages)}, offenders: {len(bad)}")
        self.assertEqual(bad[:5], [])


if __name__ == "__main__":
    unittest.main()
