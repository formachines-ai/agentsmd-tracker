"""Offline, read-only head/footer check over every committed public/ HTML page except /go/ redirects.

Per page: one <title>, one <h1>, one meta description (1-160 chars), <link rel=canonical> equal to the
page's own URL, the footer text 'Built by AI agents'. Titles must be unique across pages.
Run: python3 -B -m unittest tests.test_head -v
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
MAX_DESC = 160
FOOTER = "Built by AI agents"


def pages():
    for p in sorted(PUBLIC.rglob("*.html")):
        rel = p.relative_to(PUBLIC).as_posix()
        if rel.startswith("go/"):
            continue
        yield rel, p


def own_url(rel):
    if rel == "index.html":
        return BASE + "/"
    if rel.endswith("/index.html"):
        return BASE + "/" + rel[: -len("index.html")]
    return BASE + "/" + rel


def check(rel, text):
    errs = []
    head = text.split("</head>", 1)[0]  # SVG chart <title> elements in the body are not page titles
    titles = re.findall(r"<title>(.*?)</title>", head, re.S)
    if len(titles) != 1:
        errs.append(f"{len(titles)} <title>")
    n_h1 = len(re.findall(r"<h1[\s>]", text))
    if n_h1 != 1:
        errs.append(f"{n_h1} <h1>")
    descs = re.findall(r'<meta\s+name="description"\s+content="([^"]*)"', text)
    if len(descs) != 1:
        errs.append(f"{len(descs)} meta description")
    elif not 1 <= len(html.unescape(descs[0])) <= MAX_DESC:
        errs.append(f"description length {len(html.unescape(descs[0]))}")
    canon = re.findall(r'<link\s+rel="canonical"\s+href="([^"]*)"', text)
    if canon != [own_url(rel)]:
        errs.append(f"canonical {canon} != {own_url(rel)}")
    if FOOTER not in text:
        errs.append("footer text missing")
    return errs, (html.unescape(titles[0]).strip() if len(titles) == 1 else None)


class HeadTest(unittest.TestCase):
    def test_all_pages(self):
        failures, by_title, n = [], defaultdict(list), 0
        for rel, p in pages():
            n += 1
            errs, title = check(rel, p.read_text(encoding="utf-8"))
            if errs:
                failures.append((rel, errs))
            if title is not None:
                by_title[title].append(rel)
        dups = {t: r for t, r in by_title.items() if len(r) > 1}
        print(f"\npages checked: {n}; failures: {len(failures)}; duplicate titles: {len(dups)}")
        for rel, errs in failures[:50]:
            print("FAIL", rel, "; ".join(errs))
        for t, r in list(dups.items())[:20]:
            print("DUP", repr(t), r[:5], len(r))
        self.assertGreater(n, 1900)
        self.assertEqual(failures, [])
        self.assertEqual(dups, {})


if __name__ == "__main__":
    unittest.main()
