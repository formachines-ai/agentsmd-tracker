"""Offline, read-only: every <loc> in public/sitemap.xml must be reachable from /
by plain internal <a href> links (not /go/) within MAX_DEPTH clicks."""
import re
import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

PUBLIC = Path(__file__).resolve().parent.parent / "public"
HOST = "agentsmd.formachines.ai"
BASE = "https://" + HOST
MAX_DEPTH = 3


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            h = dict(attrs).get("href")
            if h:
                self.hrefs.append(h)


def _page(path):
    p = PUBLIC / path.lstrip("/")
    if p.is_dir():
        p = p / "index.html"
    return p if p.suffix == ".html" and p.is_file() else None


def bfs():
    depth = {"/": 0}
    frontier = ["/"]
    d = 0
    while frontier:
        d += 1
        nxt = []
        for url in frontier:
            page = _page(url)
            if not page:
                continue
            parser = _Links()
            parser.feed(page.read_text(encoding="utf-8"))
            for h in parser.hrefs:
                u = urlparse(urldefrag(urljoin(BASE + url, h))[0])
                if u.netloc != HOST or u.path.startswith("/go/") or u.path in depth:
                    continue
                depth[u.path] = d
                nxt.append(u.path)
        frontier = nxt
    return depth


class InternalLinks(unittest.TestCase):
    def test_every_sitemap_url_within_three_clicks(self):
        xml = (PUBLIC / "sitemap.xml").read_text(encoding="utf-8")
        locs = re.findall(r"<loc>([^<]+)</loc>", xml)
        self.assertTrue(locs)
        depth = bfs()
        paths = [urlparse(u).path for u in locs]
        orphans = [p for p in paths if depth.get(p, 99) > MAX_DEPTH]
        counts = Counter(depth.get(p, "unreached") for p in paths)
        print(f"\nsitemap URLs checked: {len(paths)}; per depth: {dict(sorted(counts.items(), key=str))}; "
              f"orphans: {len(orphans)}")
        self.assertEqual(orphans[:10], [], f"{len(orphans)} sitemap URLs not within {MAX_DEPTH} clicks")

    def test_robots_has_sitemap_line(self):
        txt = (PUBLIC / "robots.txt").read_text(encoding="utf-8")
        self.assertIn(f"Sitemap: {BASE}/sitemap.xml", txt.splitlines())


if __name__ == "__main__":
    unittest.main()
