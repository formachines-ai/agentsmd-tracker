"""Offline, read-only: every public/repo/<owner>/<name>/ card must be reachable
from / by plain <a href> links within 2 hops (home -> /lang/<slug>/ -> card)."""
import json
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

PUBLIC = Path(__file__).resolve().parent.parent / "public"
SITE_HOSTS = {"agentsmd.formachines.ai"}
MAX_DEPTH = 2


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            h = dict(attrs).get("href")
            if h:
                self.hrefs.append(h)


def _page_for(path):
    path = path.split("?")[0]
    if not path.startswith("/"):
        return None
    p = PUBLIC / path.lstrip("/")
    if p.is_dir():
        p = p / "index.html"
    return p if p.suffix == ".html" and p.is_file() else None


def crawl():
    seen = {"/": 0}
    frontier = ["/"]
    for depth in range(1, MAX_DEPTH + 1):
        nxt = []
        for url in frontier:
            page = _page_for(url)
            if not page:
                continue
            parser = _Links()
            parser.feed(page.read_text(encoding="utf-8"))
            for h in parser.hrefs:
                full = urldefrag(urljoin("https://agentsmd.formachines.ai" + url, h))[0]
                u = urlparse(full)
                if u.netloc not in SITE_HOSTS:
                    continue
                path = u.path
                if path not in seen:
                    seen[path] = depth
                    nxt.append(path)
        frontier = nxt
    return seen


class Reachability(unittest.TestCase):
    def test_every_card_reached_within_two_links(self):
        # Unreachable repos (moved/deleted) keep their card but are excluded from language lists by design,
        # so they are legitimately not linked from / within 2 hops; every other card must be.
        cards = sorted("/" + str(p.parent.relative_to(PUBLIC)) + "/"
                       for p in PUBLIC.glob("repo/*/*/index.html")
                       if json.loads((p.parent / "index.json").read_text(encoding="utf-8")).get("status") != "unreachable")
        seen = crawl()
        reached = [c for c in cards if c in seen]
        missing = [c for c in cards if c not in seen]
        print(f"cards found: {len(cards)}; reached from / within {MAX_DEPTH} links: {len(reached)}",
              file=sys.stderr)
        self.assertTrue(cards)
        self.assertEqual(missing, [], f"{len(missing)} unreachable, e.g. {missing[:5]}")

    def test_sitemap_lang_and_robots(self):
        base = "https://agentsmd.formachines.ai"
        locs = re.findall(r"<loc>([^<]+)</loc>", (PUBLIC / "sitemap.xml").read_text(encoding="utf-8"))
        paths = [urlparse(u).path for u in locs]
        no_file = [p for p in paths if not (PUBLIC / p.lstrip("/")).exists()
                   or ((PUBLIC / p.lstrip("/")).is_dir() and not (PUBLIC / p.lstrip("/") / "index.html").is_file())]
        # every page reachable from / or a /lang/ page: collect hrefs of / and all /lang/ pages
        linked = set()
        home_links = set()
        pages = [("/", PUBLIC / "index.html")] + [("/lang/%s/" % d.name, d / "index.html")
                                                  for d in sorted((PUBLIC / "lang").glob("*")) if d.is_dir()]
        for url, f in pages:
            parser = _Links()
            parser.feed(f.read_text(encoding="utf-8"))
            for h in parser.hrefs:
                path = urlparse(urldefrag(urljoin(base + url, h))[0]).path
                linked.add(path)
                if url == "/":
                    home_links.add(path)
        langs = sorted("/lang/%s/" % d.name for d in (PUBLIC / "lang").glob("*") if d.is_dir())
        lang_missing = [l for l in langs if l not in home_links]
        repo_paths = [p for p in paths if re.fullmatch(r"/repo/[^/]+/[^/]+/", p)]
        repo_missing = [p for p in repo_paths if p not in linked]
        robots = (PUBLIC / "robots.txt").read_text(encoding="utf-8")
        has_sitemap = ("Sitemap: " + base + "/sitemap.xml") in robots.splitlines()
        blocked = [l for l in robots.splitlines() if re.match(r"\s*Disallow:\s*/(repo|lang)/?\s*$", l)]
        print(f"sitemap URLs: {len(paths)}; /repo/ in sitemap: {len(repo_paths)}; not linked from / or /lang/: "
              f"{len(repo_missing)}; /lang/ pages: {len(langs)}, not linked from /: {len(lang_missing)}; "
              f"sitemap URLs without file: {len(no_file)}; robots Sitemap line: {has_sitemap}", file=sys.stderr)
        self.assertEqual(no_file, [], f"sitemap URLs without file: {no_file[:5]}")
        self.assertEqual(lang_missing, [])
        self.assertEqual(repo_missing, [], f"{len(repo_missing)} not linked, e.g. {repo_missing[:5]}")
        self.assertTrue(has_sitemap)
        self.assertEqual(blocked, [])


if __name__ == "__main__":
    unittest.main()
