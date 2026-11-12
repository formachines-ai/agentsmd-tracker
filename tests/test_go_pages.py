"""Offline, read-only check over the committed public/ tree (no network, no writes).

(1) every public/go/<id>/index.html has <meta name="robots" content="noindex, nofollow"> and a meta-refresh target;
(2) every <a href> to /go/ on site pages has rel containing nofollow;
(3) no /go/ URL is in sitemap.xml.
Run: python3 -B -m unittest tests.test_go_pages -v
"""
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
PUBLIC = Path(__file__).resolve().parent.parent / "public"
BASE = "https://agentsmd.formachines.ai"
META = '<meta name="robots" content="noindex, nofollow">'
A_GO = re.compile(r'<a\s[^>]*href="(?:https://agentsmd\.formachines\.ai)?/go/[^"]*"[^>]*>')


class GoPagesTest(unittest.TestCase):
    def test_go_pages_noindex(self):
        pages = sorted(PUBLIC.glob("go/*/index.html"))
        votes = sorted(PUBLIC.glob("go/vote/*/*/index.html"))
        self.assertTrue(pages and votes)
        bad = []
        for p in pages + votes:
            t = p.read_text(encoding="utf-8")
            if META not in t or not re.search(r'<meta http-equiv="refresh" content="0; url=[^"]+">', t):
                bad.append(str(p.relative_to(PUBLIC)))
        self.assertEqual(bad[:5], [])
        print(f"/go/ pages checked: {len(pages)} redirect + {len(votes)} vote")

    def test_go_links_nofollow(self):
        n, bad = 0, []
        for p in PUBLIC.rglob("*.html"):
            if p.relative_to(PUBLIC).parts[0] == "go":
                continue
            for a in A_GO.findall(p.read_text(encoding="utf-8")):
                n += 1
                m = re.search(r'rel="([^"]*)"', a)
                if not m or "nofollow" not in m.group(1).split():
                    bad.append((str(p.relative_to(PUBLIC)), a))
        self.assertTrue(n)
        self.assertEqual(bad[:5], [])
        print(f"/go/ links checked: {n}")

    def test_sitemap_has_no_go(self):
        xml = (PUBLIC / "sitemap.xml").read_text(encoding="utf-8")
        locs = re.findall(r"<loc>([^<]*)</loc>", xml)
        self.assertTrue(locs)
        self.assertEqual([l for l in locs if l.startswith(BASE + "/go/")], [])
        print(f"sitemap URLs checked: {len(locs)}")


if __name__ == "__main__":
    unittest.main()
