"""Offline link check over the committed public/ tree (read-only, no network, no writes).

Every internal href/src in every .html page and every <loc> in sitemap.xml must resolve to a file,
or to a directory with index.html. Run: python3 -B -m unittest tests.test_links  (or discover -s tests)
"""
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

sys.dont_write_bytecode = True
PUBLIC = Path(__file__).resolve().parent.parent / "public"
HOST = "agentsmd.formachines.ai"
BASE = "https://" + HOST


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src") and v:
                self.refs.append(v.strip())


def _resolve(url_path):
    """Map a URL path to an existing file in public/, or None."""
    rel = unquote(url_path).lstrip("/")
    p = PUBLIC / rel
    if rel == "" or url_path.endswith("/"):
        return p / "index.html" if (p / "index.html").is_file() else None
    if p.is_file():
        return p
    if (p / "index.html").is_file():
        return p / "index.html"
    return None


def _internal_path(ref, page_url):
    """Return URL path if ref is internal, else None."""
    if ref.startswith(("mailto:", "tel:", "javascript:", "data:", "#")):
        return None
    full = urljoin(page_url, ref)
    u = urlsplit(full)
    if u.scheme not in ("http", "https") or u.netloc != HOST:
        return None
    return u.path or "/"


class LinkTest(unittest.TestCase):
    def test_html_internal_links(self):
        broken, checked, pages = [], 0, 0
        for f in sorted(PUBLIC.rglob("*.html")):
            pages += 1
            rel = f.relative_to(PUBLIC).as_posix()
            page_url = BASE + "/" + (rel[:-len("index.html")] if rel.endswith("index.html") else rel)
            c = _Collector()
            c.feed(f.read_text(encoding="utf-8", errors="replace"))
            for ref in c.refs:
                path = _internal_path(ref, page_url)
                if path is None:
                    continue
                checked += 1
                if _resolve(path) is None:
                    broken.append((rel, ref))
        print(f"\nlinks: {checked} internal href/src checked in {pages} html pages; broken: {len(broken)}")
        self.assertGreater(checked, 0)
        self.assertEqual(broken[:20], [], f"{len(broken)} broken internal links")

    def test_sitemap_locs(self):
        xml = (PUBLIC / "sitemap.xml").read_text(encoding="utf-8")
        locs = re.findall(r"<loc>([^<]+)</loc>", xml)
        broken = []
        for loc in locs:
            u = urlsplit(loc.strip())
            if u.netloc != HOST or _resolve(u.path or "/") is None:
                broken.append(loc)
        print(f"\nsitemap: {len(locs)} <loc> checked; broken: {len(broken)}")
        self.assertGreater(len(locs), 0)
        self.assertEqual(broken[:20], [], f"{len(broken)} broken sitemap URLs")


if __name__ == "__main__":
    unittest.main()
