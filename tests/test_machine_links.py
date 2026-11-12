"""Offline link check over machine outputs in the committed public/ tree (read-only, no network).

Sources: feed.xml, llms.txt, stats.json, today.json, repo/*/*/index.json. Every site URL
(https://agentsmd.formachines.ai/... or a string starting with '/') must map to a file or a directory
with index.html. Queries and fragments are dropped.
Run: python3 -B -m unittest tests.test_machine_links
"""
import html
import json
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_links import PUBLIC, HOST, BASE, _resolve  # noqa: E402

_ABS = re.compile(r"https://" + re.escape(HOST) + r"(?:/[^\s<>\"'\)\]]*)?")
_REL = re.compile(r"(?<![\w:/.>])/[^\s<>\"'\)\]]*")  # bare /path tokens in text


def _norm(u):
    if u.startswith("/"):
        u = BASE + u
    s = urlsplit(u)
    return s.path or "/"


def _from_json(node, out):
    if isinstance(node, dict):
        for v in node.values():
            _from_json(v, out)
    elif isinstance(node, list):
        for v in node:
            _from_json(v, out)
    elif isinstance(node, str):
        if node.startswith(BASE + "/") or node == BASE or (node.startswith("/") and not node.startswith("//")):
            out.append(node.strip())


def _from_text(text, out, rel=False):  # rel=True: plain text (llms.txt), where <x> marks a template
    text = html.unescape(text)
    pats = [_ABS] + ([_REL] if rel else [])
    for pat in pats:
        for m in pat.finditer(text):
            # documentation templates such as /repo/<owner>/<name>/ are not real URLs
            if rel and text[m.end():m.end() + 1] == "<":
                continue
            out.append(m.group(0).rstrip(".,:;"))


def _sources():
    src = {}
    out = []
    _from_text((PUBLIC / "feed.xml").read_text(encoding="utf-8"), out)
    src["feed.xml"] = out
    out = []
    _from_text((PUBLIC / "llms.txt").read_text(encoding="utf-8"), out, rel=True)
    src["llms.txt"] = out
    for name in ("stats.json", "today.json"):
        out = []
        _from_json(json.loads((PUBLIC / name).read_text(encoding="utf-8")), out)
        src[name] = out
    out = []
    files = sorted(PUBLIC.glob("repo/*/*/index.json"))
    for f in files:
        _from_json(json.loads(f.read_text(encoding="utf-8")), out)
    src["repo/*/*/index.json (%d files)" % len(files)] = out
    return src


class MachineLinkTest(unittest.TestCase):
    def test_machine_output_urls(self):
        broken = []
        for name, urls in _sources().items():
            bad = [u for u in urls if _resolve(_norm(u)) is None]
            print(f"\nmachine links: {name}: {len(urls)} URLs checked; broken: {len(bad)}")
            broken += [(name, u) for u in bad]
            self.assertGreater(len(urls), 0, f"no site URLs found in {name}")
        self.assertEqual(broken[:20], [], f"{len(broken)} broken URLs in machine outputs")


if __name__ == "__main__":
    unittest.main()
