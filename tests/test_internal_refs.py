"""Offline, read-only: every internal href/src in public/**/*.html, and every URL in
sitemap.xml, feed.xml and llms.txt, must map to a file in public/ (path/ = path/index.html)."""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, unquote

PUBLIC = Path(__file__).resolve().parent.parent / "public"
HOST = "agentsmd.formachines.ai"


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("a", "link") and a.get("href"):
            self.refs.append(a["href"])
        elif tag in ("img", "script") and a.get("src"):
            self.refs.append(a["src"])


def internal_path(ref, page_url="/"):
    """Return the site path for an internal ref, or None if external/non-http."""
    u = urlparse(ref.strip())
    if u.scheme in ("http", "https"):
        if u.netloc != HOST:
            return None
        path = u.path or "/"
    elif u.scheme or u.netloc:
        return None
    else:
        path = u.path
        if not path:
            return None  # fragment/query only
        if not path.startswith("/"):
            base = page_url if page_url.endswith("/") else page_url.rsplit("/", 1)[0] + "/"
            path = base + path
    return unquote(path)


def resolves(path):
    p = PUBLIC / path.lstrip("/")
    if path.endswith("/"):
        return (p / "index.html").is_file()
    return p.is_file() or (p / "index.html").is_file()


def collect():
    refs = []  # (source, ref, path)
    for html in sorted(PUBLIC.rglob("*.html")):
        rel = "/" + html.relative_to(PUBLIC).as_posix()
        page_url = rel[: -len("index.html")] if rel.endswith("/index.html") else rel
        parser = _Refs()
        parser.feed(html.read_text(encoding="utf-8"))
        for r in parser.refs:
            p = internal_path(r, page_url)
            if p is not None:
                refs.append((rel, r, p))
    for name, rx in (("sitemap.xml", r"<loc>\s*([^<\s]+)\s*</loc>"),
                     ("feed.xml", r"<(?:link|guid)[^>]*>\s*(https?://[^<\s]+)\s*</"),
                     ("llms.txt", r"https?://[^\s)>\]\"']+")):
        text = (PUBLIC / name).read_text(encoding="utf-8")
        found = re.findall(rx, text)
        for r in found:
            r = r.rstrip(".,;")
            if "<" in r or ">" in r:
                continue  # URL template placeholder, not a link
            p = internal_path(r)
            if p is not None:
                refs.append((name, r, p))
    return refs


class InternalRefs(unittest.TestCase):
    def test_all_internal_refs_resolve(self):
        refs = collect()
        misses = sorted({(s, r) for s, r, p in refs if not resolves(p)})
        print(f"\ninternal refs checked: {len(refs)}; misses: {len(misses)}")
        for s, r in misses:
            print(f"  MISS {s} -> {r}")
        self.assertGreater(len(refs), 100)
        self.assertEqual(misses, [])

    def test_favicons_exist(self):
        for f in ("favicon.ico", "favicon.svg"):
            self.assertTrue((PUBLIC / f).is_file(), f)


if __name__ == "__main__":
    unittest.main()
