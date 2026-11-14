"""Offline, read-only sitemap check over the committed public/ tree (no network, no writes).

(1) every /lang/<slug>/ page linked from the home page is in sitemap.xml and exists;
(2) every <url> has <lastmod> YYYY-MM-DD; repos added in today.json carry today.json's date;
    fewer than half of the /repo/ URLs carry the stats.json generated date.
Run: python3 -B -m unittest tests.test_sitemap -v
"""
import json
import re
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
PUBLIC = Path(__file__).resolve().parent.parent / "public"
BASE = "https://agentsmd.formachines.ai"


def _entries():
    xml = (PUBLIC / "sitemap.xml").read_text(encoding="utf-8")
    blocks = re.findall(r"<url>(.*?)</url>", xml, re.S)
    out = []
    for b in blocks:
        loc = re.search(r"<loc>([^<]*)</loc>", b)
        lm = re.search(r"<lastmod>([^<]*)</lastmod>", b)
        out.append((loc.group(1) if loc else None, lm.group(1) if lm else None))
    return out


class SitemapTest(unittest.TestCase):
    def test_lang_pages_listed(self):
        home = (PUBLIC / "index.html").read_text(encoding="utf-8")
        slugs = set(re.findall(r'href="/lang/([a-z0-9-]+)/"', home))
        locs = {l for l, _ in _entries()}
        self.assertTrue(slugs)
        for s in slugs:
            self.assertIn(f"{BASE}/lang/{s}/", locs)
            self.assertTrue((PUBLIC / "lang" / s / "index.html").is_file(), s)
        print(f"lang pages linked from home and in sitemap: {len(slugs)}")

    def test_lastmod(self):
        ent = _entries()
        for loc, lm in ent:
            self.assertTrue(loc, "url without loc")
            self.assertRegex(lm or "", r"^\d{4}-\d{2}-\d{2}$", loc)
        gen = json.loads((PUBLIC / "stats.json").read_text())["generated"][:10]
        today = json.loads((PUBLIC / "today.json").read_text())
        repos = {l: lm for l, lm in ent if "/repo/" in l}
        for a in today.get("added", []):
            u = f"{BASE}/repo/{a['owner']}/{a['name']}/"
            self.assertEqual(repos.get(u), today["generated"][:10], u)
        stamped = sum(1 for lm in repos.values() if lm == gen)
        self.assertLess(stamped * 2, len(repos))
        by = Counter(repos.values())
        for loc, lm in ent:
            self.assertLessEqual(lm, gen, loc)
        self.assertEqual(len(ent), len({l for l, _ in ent}))
        xml = (PUBLIC / "sitemap.xml").read_text(encoding="utf-8")
        self.assertEqual(xml.count("<url>"), xml.count("<lastmod>"))
        for u in ("/", "/lang/python/"):
            self.assertEqual(dict(ent)[BASE + u], gen, u)
        mp = repos.get(f"{BASE}/repo/baomidou/mybatis-plus/")
        if mp is not None:
            self.assertGreaterEqual(mp, "2026-11-13")
        older = sorted((lm, l) for l, lm in repos.items() if lm < gen)
        self.assertTrue(older)
        print(f"urls checked={len(ent)} older_than_generated={len(older)} e.g. {older[0][1]} {older[0][0]}")
        print(f"urls={len(ent)} repo_urls={len(repos)} stats_generated={gen} repo_lastmod_equal_generated={stamped}")
        print("repo lastmod counts:", dict(sorted(by.items())))


if __name__ == "__main__":
    unittest.main()
