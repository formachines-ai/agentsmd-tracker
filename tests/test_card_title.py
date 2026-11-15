"""Every public/repo/**/index.html <title> is 10-70 chars and its status equals the repo's index.json. Offline, read-only."""
import html
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RE = re.compile(r"AGENTS(?:\.md)? (yes|no|not checked), CLAUDE(?:\.md)? (yes|no|not checked)")


class CardTitle(unittest.TestCase):
    def test_titles(self):
        n, bad = 0, []
        for page in sorted((REPO / "public" / "repo").glob("*/*/index.html")):
            m = re.search(r"<title>(.*?)</title>", page.read_text(encoding="utf-8"), re.S)
            title = html.unescape(m.group(1)) if m else ""
            doc = json.loads((page.parent / "index.json").read_text(encoding="utf-8"))
            st = lambda p: {True: "yes", False: "no"}.get(doc["files"].get(p, {}).get("present"), "not checked")
            sm = RE.search(title)
            n += 1
            if not 10 <= len(title) <= 70 or not sm or sm.groups() != (st("AGENTS.md"), st("CLAUDE.md")):
                bad.append((str(page.relative_to(REPO)), len(title), title))
        print(f"cards checked: {n}, offenders: {len(bad)}")
        self.assertGreater(n, 1000)
        self.assertEqual(bad, [], bad[:5])

    def test_card_title_function(self):
        import build
        t = build.card_title("a" * 30 + "/" + "b" * 39, "yes", "no")
        self.assertLessEqual(len(t), 70)
        self.assertIn("…", t)
        self.assertIn("yes", t)


if __name__ == "__main__":
    unittest.main()
