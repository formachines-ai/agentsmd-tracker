"""Offline, read-only: every internal href/src in public/**/index.html, sitemap.xml
and feed.xml must resolve to a file in public/ (directory URL -> <dir>/index.html)."""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

PUBLIC = Path(__file__).resolve().parent.parent / "public"
HOST = "agentsmd.formachines.ai"
BASE = "https://" + HOST


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src") and v:
                self.refs.append(v)


def resolve(page_url, ref):
    """Return the site path for an internal ref, or None if external/non-http."""
    u = urlparse(urljoin(page_url, ref.strip()))
    if u.scheme not in ("http", "https") or u.netloc != HOST:
        return None
    return unquote(u.path) or "/"


def exists(path):
    p = PUBLIC / path.lstrip("/")
    if path.endswith("/") or p.is_dir():
        return (p / "index.html").is_file()
    return p.is_file()


def collect():
    """Yield (source file, ref, target path)."""
    for f in sorted(PUBLIC.rglob("index.html")):
        url = BASE + "/" + f.parent.relative_to(PUBLIC).as_posix().strip(".") 
        url = url.rstrip("/") + "/"
        parser = _Refs()
        parser.feed(f.read_text(encoding="utf-8"))
        for r in parser.refs:
            t = resolve(url, r)
            if t is not None:
                yield f, r, t
    for name in ("sitemap.xml", "feed.xml"):
        text = (PUBLIC / name).read_text(encoding="utf-8")
        urls = re.findall(r"<(?:loc|link)[^>]*>\s*([^<\s]+)\s*<", text)
        urls += re.findall(r'(?:href|url|src)="([^"]+)"', text)
        for r in urls:
            t = resolve(BASE + "/", r.replace("&amp;", "&"))
            if t is not None:
                yield PUBLIC / name, r, t


class NoBrokenInternalLinks(unittest.TestCase):
    def test_all_internal_targets_exist(self):
        pages = len(list(PUBLIC.rglob("index.html"))) + 2
        total, bad = 0, []
        for f, r, t in collect():
            total += 1
            if not exists(t):
                bad.append(f"{f.relative_to(PUBLIC)}: {r} -> {t}")
        print(f"\nchecked {pages} pages, {total} internal links, {len(bad)} offenders")
        for b in bad[:100]:
            print("  BROKEN", b)
        self.assertGreater(total, 0)
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
