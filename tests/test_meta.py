"""Every HTML page (except /go/) has one <title> and one meta description (50-160 chars), both unique;
/ and /lang/<slug>/ numbers match stats.json. Offline, read-only."""
import json
import re
import unittest
from collections import defaultdict
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent / "public"
SVG = re.compile(r"<svg\b.*?</svg>", re.S)
TITLE = re.compile(r"<title>(.*?)</title>", re.S)
DESC = re.compile(r'<meta name="description" content="([^"]*)"')
BAD_WORDS = re.compile(r"\b(best|top-rated|leading)\b", re.I)


def pages():
    return [p for p in sorted(PUBLIC.rglob("*.html")) if p.relative_to(PUBLIC).parts[0] != "go"]


def meta(p: Path):
    s = SVG.sub("", p.read_text(encoding="utf-8"))
    return TITLE.findall(s), DESC.findall(s)


class MetaTest(unittest.TestCase):
    def test_unique_title_and_description(self):
        titles, descs = defaultdict(list), defaultdict(list)
        ps = pages()
        for p in ps:
            t, d = meta(p)
            self.assertEqual(len(t), 1, f"{p}: {len(t)} titles")
            self.assertEqual(len(d), 1, f"{p}: {len(d)} descriptions")
            self.assertTrue(t[0].strip(), p)
            self.assertTrue(50 <= len(d[0]) <= 160, f"{p}: description length {len(d[0])}")
            if "repo" not in p.relative_to(PUBLIC).parts[:1]:  # card text contains repo names
                self.assertIsNone(BAD_WORDS.search(d[0]), p)
            titles[t[0]].append(p)
            descs[d[0]].append(p)
        self.assertEqual([v for v in titles.values() if len(v) > 1], [])
        self.assertEqual([v for v in descs.values() if len(v) > 1], [])
        print(f"meta: {len(ps)} pages checked, 0 duplicate titles, 0 duplicate descriptions")

    def test_numbers_match_stats_json(self):
        st = json.loads((PUBLIC / "stats.json").read_text(encoding="utf-8"))
        day = st["generated"][:10]
        d = meta(PUBLIC / "index.html")[1][0]
        m = re.match(r"([\d,]+) of ([\d,]+) .*?\(([\d.]+) %\) on (\d{4}-\d\d-\d\d)\.", d)
        self.assertIsNotNone(m, d)
        self.assertEqual(m.group(4), day)
        self.assertEqual(int(m.group(1).replace(",", "")), st["counts"]["AGENTS.md"])
        self.assertEqual(int(m.group(2).replace(",", "")), st["scanned"])
        self.assertEqual(float(m.group(3)), st["shares"]["AGENTS.md"])

    def test_lang_pages(self):
        st = json.loads((PUBLIC / "stats.json").read_text(encoding="utf-8"))
        day = st["generated"][:10]
        n = 0
        for p in sorted((PUBLIC / "lang").glob("*/index.html")):
            d = meta(p)[1][0]
            m = re.match(r"(.+?): AGENTS.md in (\d+) of (\d+) top repos \(([\d.]+) %\)", d)
            self.assertIsNotNone(m, d)
            v = st["by_language"][m.group(1)]
            self.assertEqual((int(m.group(2)), int(m.group(3))), (v["AGENTS.md"], v["repos"]))
            self.assertEqual(float(m.group(4)), round(100 * v["AGENTS.md"] / v["repos"], 1))
            self.assertIn(day, d)
            n += 1
        self.assertGreater(n, 0)


if __name__ == "__main__":
    unittest.main()
