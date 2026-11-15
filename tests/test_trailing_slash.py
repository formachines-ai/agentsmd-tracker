"""Offline, read-only: every internal URL to a directory page (/, /lang/<slug>/, /repo/<owner>/<name>/,
/legal/, /brand/, /go/<id>/) in public/**/*.html, sitemap.xml, feed.xml and llms.txt ends with '/'
before any query or fragment. Prints the refs checked and the offenders."""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

PUBLIC = Path(__file__).resolve().parent.parent / "public"
HOST = "agentsmd.formachines.ai"
DIR_RE = re.compile(r"^/(lang/[^/]+|repo/[^/]+/[^/]+|legal|brand|go/[^/]+(/[^/]+)*)$")
ABS_RE = re.compile(r"https?://" + re.escape(HOST) + r"(/[^\s\"'<>)\]]*)?")
REL_RE = re.compile(r"(?<![\w/.:])(/(?:lang|repo|legal|brand|go)/[^\s\"'<>)\]`,]*)")


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src", "content") and v:
                if k != "content" or v.startswith(("/", "http")):
                    self.refs.append(v)
                elif "url=" in v.lower():
                    self.refs.append(v.split("=", 1)[1])


def dir_path(ref):
    """Path of an internal ref (before ? and #) or None if external."""
    u = urlparse(ref.strip())
    if u.scheme in ("http", "https"):
        if u.netloc != HOST:
            return None
    elif u.scheme or u.netloc or not u.path.startswith("/"):
        return None
    return u.path


def collect():
    refs = []  # (file, ref)
    for f in sorted(PUBLIC.rglob("*.html")):
        p = _Refs()
        p.feed(f.read_text(encoding="utf-8"))
        refs += [(f, r) for r in p.refs]
    for name in ("sitemap.xml", "feed.xml", "llms.txt"):
        t = (PUBLIC / name).read_text(encoding="utf-8")
        refs += [(PUBLIC / name, m.group(0)) for m in ABS_RE.finditer(t)]
        refs += [(PUBLIC / name, m.group(1)) for m in REL_RE.finditer(t) if "<" not in m.group(1)]
    return refs


class TrailingSlash(unittest.TestCase):
    def test_directory_urls_end_with_slash(self):
        checked, bad = 0, []
        for f, ref in collect():
            path = dir_path(ref)
            if path is None or not (path == "/" or DIR_RE.match(path) or re.match(r"^/(lang|repo|legal|brand|go)(/|$)", path)):
                continue
            last = path.rsplit("/", 1)[-1]
            if "." in last and not path.endswith("/"):
                continue  # a file such as index.json
            checked += 1
            if not path.endswith("/"):
                bad.append(f"{f.relative_to(PUBLIC)}: {ref}")
        print(f"\ntrailing-slash: {checked} directory refs checked, {len(bad)} offenders")
        for b in bad[:50]:
            print("  OFFENDER", b)
        self.assertGreater(checked, 100)
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
