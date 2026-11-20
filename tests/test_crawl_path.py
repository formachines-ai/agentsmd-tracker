"""Offline: build with --no-scan into a temp dir, then assert every /repo/ and /lang/ URL of sitemap.xml is
reachable from / through plain internal <a href> links in at most 2 hops. Nothing is written to the checkout."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

REPO = Path(__file__).resolve().parent.parent
HOST = "agentsmd.formachines.ai"
BASE = "https://" + HOST


class _A(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        h = dict(attrs).get("href") if tag == "a" else None
        if h:
            self.hrefs.append(h)


class CrawlPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="crawl-"))
        shutil.copy(REPO / "build.py", cls.tmp / "build.py")
        shutil.copytree(REPO / "static", cls.tmp / "static")
        shutil.copytree(REPO / "data", cls.tmp / "data")
        subprocess.run(["chmod", "-R", "u+w", str(cls.tmp)], check=True)
        (cls.tmp / "public").mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "BUILD_NOW")}
        r = subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=cls.tmp, capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr + r.stdout
        cls.pub = cls.tmp / "public"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def links(self, path):
        p = self.pub / path.lstrip("/")
        if p.is_dir():
            p = p / "index.html"
        if not p.is_file() or p.suffix != ".html":
            return []
        a = _A()
        a.feed(p.read_text(encoding="utf-8"))
        out = []
        for h in a.hrefs:
            u = urlparse(urldefrag(urljoin(BASE + path, h))[0])
            if u.netloc == HOST:
                out.append(u.path)
        return out

    def test_sitemap_repo_and_lang_within_two_hops(self):
        locs = re.findall(r"<loc>([^<]+)</loc>", (self.pub / "sitemap.xml").read_text(encoding="utf-8"))
        targets = [urlparse(u).path for u in locs if re.match(r"/(repo|lang)/", urlparse(u).path)]
        seen, frontier = {"/": 0}, ["/"]
        for depth in (1, 2):
            nxt = []
            for url in frontier:
                for t in self.links(url):
                    if t not in seen:
                        seen[t] = depth
                        nxt.append(t)
            frontier = nxt
        missing = [t for t in targets if t not in seen]
        n_lang = sum(t.startswith("/lang/") for t in targets)
        print(f"sitemap /repo/ + /lang/ URLs: {len(targets)} (lang {n_lang}); reached in <=2 hops: {len(targets) - len(missing)}; "
              f"missing: {len(missing)}", file=sys.stderr)
        self.assertGreater(n_lang, 0)
        self.assertGreater(len(targets), n_lang)
        self.assertEqual(missing, [], f"{len(missing)} not reachable, e.g. {missing[:5]}")


if __name__ == "__main__":
    unittest.main()
