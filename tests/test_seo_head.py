"""Offline, read-only SEO head check over the committed public/ tree: sitemap lastmod, unique title/description, self-canonical.
Run: python3 -B -m unittest tests.test_seo_head -v
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


def pages():
    for p in sorted(PUBLIC.rglob("index.html")):
        rel = p.relative_to(PUBLIC).parent.as_posix()
        if rel.startswith("go/") or rel == "go":
            continue
        yield p, (BASE + "/" if rel == "." else f"{BASE}/{rel}/")


class SeoHeadTest(unittest.TestCase):
    def test_sitemap_lastmod(self):
        xml = (PUBLIC / "sitemap.xml").read_text(encoding="utf-8")
        blocks = re.findall(r"<url>(.*?)</url>", xml, re.S)
        bad = [b for b in blocks if not re.search(r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", b)]
        self.assertTrue(blocks)
        self.assertEqual(bad[:5], [], f"{len(bad)} urls without YYYY-MM-DD lastmod")
        print(f"sitemap urls={len(blocks)} with lastmod={len(blocks) - len(bad)}")

    def test_head(self):
        titles, descs, errs, n = defaultdict(list), defaultdict(list), [], 0
        for p, url in pages():
            n += 1
            s = p.read_text(encoding="utf-8")
            t, d, c = TITLE.search(s), DESC.search(s), CANON.findall(s)
            t = html.unescape(t.group(1)).strip() if t else ""
            d = html.unescape(d.group(1)).strip() if d else ""
            if not t:
                errs.append(f"{url}: missing title")
            if not d:
                errs.append(f"{url}: missing description")
            if c != [url]:
                errs.append(f"{url}: canonical {c}")
            titles[t].append(url)
            descs[d].append(url)
        for k, v in titles.items():
            if k and len(v) > 1:
                errs.append(f"duplicate title {k!r}: {v[:3]}")
        for k, v in descs.items():
            if k and len(v) > 1:
                errs.append(f"duplicate description {k!r}: {v[:3]}")
        print(f"pages checked: {n}, offenders: {len(errs)}")
        self.assertEqual(errs[:10], [], f"{len(errs)} offenders")


if __name__ == "__main__":
    unittest.main()
