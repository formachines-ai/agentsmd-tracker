"""Offline, read-only guard: every <table> sits in .table-wrap, viewport meta present,
no width/min-width above 375px on body/main/table."""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
VIEWPORT = "width=device-width, initial-scale=1"


class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.tables, self.bad, self.viewport = [], 0, 0, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("name") == "viewport" and a.get("content") == VIEWPORT:
            self.viewport = True
        if tag == "table":
            self.tables += 1
            if not any("table-wrap" in (c or "").split() for _, c in self.stack):
                self.bad += 1
        if tag not in ("meta", "link", "br", "img", "hr", "input", "path", "circle", "rect", "polyline", "line"):
            self.stack.append((tag, a.get("class")))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


class MobileTables(unittest.TestCase):
    def test_pages(self):
        pages = sorted(PUBLIC.rglob("index.html"))
        self.assertTrue(pages)
        tables = 0
        for f in pages:
            p = P()
            p.feed(f.read_text(encoding="utf-8"))
            rel = f.relative_to(PUBLIC)
            self.assertTrue(p.viewport, f"{rel}: viewport meta missing")
            self.assertEqual(p.bad, 0, f"{rel}: <table> outside .table-wrap")
            tables += p.tables
        self.assertGreater(tables, 0)
        print(f"mobile tables: {len(pages)} pages, {tables} tables")

    def test_css(self):
        css = re.sub(r"/\*.*?\*/", "", (PUBLIC / "style.css").read_text(encoding="utf-8"), flags=re.S)
        self.assertTrue(any("table-wrap" in sel and re.search(r"overflow-x\s*:\s*auto", body)
                            for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)),
                        ".table-wrap overflow-x:auto missing")
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if not any(s.strip() in ("body", "main", "table") for s in sel.split(",")):
                continue
            for m in re.finditer(r"(?<![-\w])(min-width|width)\s*:\s*([\d.]+)px", body):
                self.assertLessEqual(float(m.group(2)), 375, f"{sel.strip()} {m.group(0)}")


if __name__ == "__main__":
    unittest.main()
