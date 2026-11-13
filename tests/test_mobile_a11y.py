"""Offline, read-only mobile (375 px) and accessibility check over the committed public/ tree.

Every .html page except /go/ redirects: <html lang="en">; viewport meta with width=device-width;
every <table> inside an overflow-x:auto element (class rule in style.css) or itself overflow-x:auto;
no inline/attribute width over 375px; every <img> has alt; no link with empty text.
Run: python3 -B -m unittest tests.test_mobile_a11y -v
"""
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.dont_write_bytecode = True
PUBLIC = Path(__file__).resolve().parent.parent / "public"
MAX_W = 375
VOID = {"meta", "link", "br", "img", "hr", "input", "source", "area", "base", "col", "wbr", "path", "circle", "rect", "line"}


def scroll_classes():
    css = (PUBLIC / "style.css").read_text(encoding="utf-8")
    out = set()
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if re.search(r"overflow(-x)?\s*:\s*(auto|scroll)", body):
            out.update(re.findall(r"\.([\w-]+)", sel))
    return out


class Page(HTMLParser):
    def __init__(self, scroll):
        super().__init__(convert_charrefs=True)
        self.scroll, self.fails = scroll, []
        self.stack, self.lang, self.viewport = [], None, False
        self.a = None  # [has_label, text]
        self.svg = 0

    def _label(self, a):
        return bool((a.get("aria-label") or a.get("title") or "").strip())

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "meta" and a.get("name") == "viewport" and "width=device-width" in (a.get("content") or ""):
            self.viewport = True
        style = a.get("style") or ""
        for w in re.findall(r"(?<![\w-])(?:min-)?width\s*:\s*(\d+(?:\.\d+)?)px", style):
            if float(w) > MAX_W:
                self.fails.append(f"inline width {w}px on <{tag}>")
        if tag in ("img", "svg", "table", "td", "th", "div", "canvas") and (a.get("width") or "").strip().isdigit() \
                and int(a["width"]) > MAX_W and not (tag == "svg" and "viewBox" in a and "max-width" in style):
            if tag != "svg":
                self.fails.append(f"width attribute {a['width']} on <{tag}>")
        if tag == "img" and a.get("alt") is None:
            self.fails.append("img without alt")
        if tag == "img" and self.a is not None and (a.get("alt") or "").strip():
            self.a[0] = True
        if tag == "svg":
            self.svg += 1
        if tag == "a":
            self.a = [self._label(a), ""]
        if tag == "table":
            ok = False
            for t, cls, st in reversed(self.stack):
                if (set(cls) & self.scroll) or re.search(r"overflow(-x)?\s*:\s*(auto|scroll)", st):
                    ok = True
                    break
            if not ok and (set((a.get("class") or "").split()) & self.scroll):
                ok = True
            if not ok:
                self.fails.append("table not inside an overflow-x:auto wrapper")
        if tag not in VOID:
            self.stack.append((tag, (a.get("class") or "").split(), style))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == "svg":
            self.svg -= 1
        if tag == "a" and self.a is not None:
            if not self.a[0] and not self.a[1].strip():
                self.fails.append("link with empty text")
            self.a = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, d):
        if self.a is not None:
            self.a[1] += d


def pages():
    return sorted(p for p in PUBLIC.rglob("*.html") if "go" not in p.relative_to(PUBLIC).parts[:1])


class MobileA11y(unittest.TestCase):
    def test_all_pages(self):
        scroll = scroll_classes()
        self.assertIn("scroll", scroll)
        files = pages()
        self.assertGreater(len(files), 100)
        failures = []
        for p in files:
            pg = Page(scroll)
            pg.feed(p.read_text(encoding="utf-8"))
            f = list(pg.fails)
            if pg.lang != "en":
                f.append(f"html lang={pg.lang!r}")
            if not pg.viewport:
                f.append("no viewport width=device-width")
            for x in sorted(set(f)):
                failures.append(f"/{p.relative_to(PUBLIC).as_posix()}: {x}")
        print(f"\npages checked: {len(files)}; failures: {len(failures)}")
        for x in failures[:50]:
            print("FAIL", x)
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
