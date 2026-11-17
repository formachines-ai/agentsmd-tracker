"""Offline, read-only: robots.txt disallows /go/ and every /go/ href carries rel=nofollow."""
import re
import unittest
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent / "public"
A_TAG = re.compile(r"<a\b[^>]*>", re.I)
HREF = re.compile(r'href="((?:https://agentsmd\.formachines\.ai)?/go/[^"]*)"')
REL = re.compile(r'rel="([^"]*)"')


class GoNofollow(unittest.TestCase):
    def test_robots(self):
        txt = (PUBLIC / "robots.txt").read_text()
        lines = [l.strip() for l in txt.splitlines()]
        self.assertIn("Disallow: /go/", lines)
        self.assertTrue(any(l.startswith("Sitemap:") for l in lines))
        for bad in ("Disallow: /", "Disallow: /repo/", "Disallow: /lang/"):
            self.assertNotIn(bad, lines)

    def test_every_go_href_nofollow(self):
        checked, missing = 0, []
        for p in sorted(PUBLIC.rglob("index.html")) + [PUBLIC / "404.html"]:
            if not p.exists():
                continue
            for m in A_TAG.finditer(p.read_text(encoding="utf-8", errors="replace")):
                tag = m.group(0)
                if HREF.search(tag):
                    checked += 1
                    r = REL.search(tag)
                    if not r or "nofollow" not in r.group(1).split():
                        missing.append((str(p.relative_to(PUBLIC)), tag))
        self.assertGreater(checked, 0)
        self.assertEqual(missing[:5], [], f"{len(missing)} of {checked} /go/ hrefs lack nofollow")


if __name__ == "__main__":
    unittest.main()
