"""Offline, read-only indexability basics over the committed public/ tree (T-0211).
Run: python3 -B -m unittest tests.test_seo_basics -v
"""
import html
import re
import sys
import unittest
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
PUBLIC = Path(__file__).resolve().parent.parent / "public"
BASE = "https://agentsmd.formachines.ai"
TITLE = re.compile(r"<title>(.*?)</title>", re.S)
DESC = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"')
CANON = re.compile(r'<link\b[^>]*\brel="canonical"[^>]*\bhref="([^"]*)"')


def content_pages():
    for p in sorted(PUBLIC.rglob("index.html")):
        rel = p.relative_to(PUBLIC).parent.as_posix()
        if rel == "go" or rel.startswith("go/"):
            continue
        yield p, (BASE + "/" if rel == "." else f"{BASE}/{rel}/")


class SeoBasicsTest(unittest.TestCase):
    def test_robots(self):
        s = (PUBLIC / "robots.txt").read_text(encoding="utf-8")
        self.assertIn(f"Sitemap: {BASE}/sitemap.xml", s)
        self.assertIn("Disallow: /go/", s)

    def test_sitemap(self):
        xml = (PUBLIC / "sitemap.xml").read_text(encoding="utf-8")
        blocks = re.findall(r"<url>(.*?)</url>", xml, re.S)
        self.assertTrue(blocks)
        bad = []
        for b in blocks:
            loc = re.search(r"<loc>(.*?)</loc>", b).group(1)
            if not loc.startswith(BASE + "/") or loc.startswith(BASE + "/go/"):
                bad.append(f"{loc}: go or foreign url")
            if not re.search(r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", b):
                bad.append(f"{loc}: no lastmod")
        self.assertEqual(bad[:5], [], f"{len(bad)} sitemap offenders")

    def test_head_unique_and_canonical(self):
        titles, descs, errs, n = defaultdict(list), defaultdict(list), [], 0
        for p, url in content_pages():
            n += 1
            s = p.read_text(encoding="utf-8")
            t, d, c = TITLE.search(s), DESC.search(s), CANON.findall(s)
            t = html.unescape(t.group(1)).strip() if t else ""
            d = html.unescape(d.group(1)).strip() if d else ""
            if not t or not d:
                errs.append(f"{url}: missing title/description")
            if c != [url]:
                errs.append(f"{url}: canonical {c}")
            titles[t].append(url)
            descs[d].append(url)
        for k, v in list(titles.items()) + list(descs.items()):
            if k and len(v) > 1:
                errs.append(f"duplicate {k!r}: {v[:3]}")
        print(f"pages checked: {n}, offenders: {len(errs)}")
        self.assertEqual(errs[:10], [], f"{len(errs)} offenders")

    def test_every_card_linked_from_a_lang_page(self):
        cards = {f"/repo/{p.parent.parent.name}/{p.parent.name}/" for p in (PUBLIC / "repo").glob("*/*/index.html")}
        linked = set()
        for p in (PUBLIC / "lang").glob("*/index.html"):
            linked |= set(re.findall(r'href="(/repo/[^"/]+/[^"/]+/)"', p.read_text(encoding="utf-8")))
        missing = sorted(cards - linked)
        print(f"cards: {len(cards)}, not linked from any /lang/ page: {len(missing)}")
        self.assertTrue(cards)
        self.assertEqual(missing[:5], [], f"{len(missing)} cards not linked")


if __name__ == "__main__":
    unittest.main()
