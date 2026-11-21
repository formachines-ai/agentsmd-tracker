"""T-0221. Offline: build the real data/ with --no-scan into a temp dir, collect every same-site URL emitted by
sitemap.xml, llms.txt, feed.xml, stats.json, today.json, repo/*/*/index.json and every HTML page (absolute
https://agentsmd.formachines.ai/... and root-relative href/src), and assert each maps to a generated file.
Strict: a URL that names a directory must end with '/' (a bare /lang/php is a defect). Nothing is written to the checkout."""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO = Path(__file__).resolve().parent.parent
HOST = "https://agentsmd.formachines.ai"
ABS = re.compile(re.escape(HOST) + r"(?:/[^\s<>\"'\)\]\\]*)?")
REL_ATTR = re.compile(r'\b(?:href|src)="(/[^"]*)"')
REL_TEXT = re.compile(r"(?<![\w:/.>])/[A-Za-z0-9_.\-][^\s<>\"'\)\]]*")


class EmittedUrls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="emitted-"))
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

    def _problem(self, url):
        s = urlsplit(url)
        path = s.path or "/"
        rel = unquote(path).lstrip("/")
        p = self.pub / rel
        if path.endswith("/") or rel == "":
            return None if (p / "index.html").is_file() else "no index.html"
        if p.is_file():
            return None
        if (p / "index.html").is_file():
            return "directory URL without trailing slash"
        return "no such file"

    def _check(self, name, urls):
        bad = [(u, self._problem(u)) for u in urls if u.startswith(HOST) or u.startswith("/")]
        bad = [(u, w) for u, w in bad if w]
        self.assertEqual(bad[:10], [], f"{name}: {len(bad)} bad of {len(urls)}")
        return len(urls)

    def _json_urls(self, node, out):
        if isinstance(node, dict):
            for v in node.values():
                self._json_urls(v, out)
        elif isinstance(node, list):
            for v in node:
                self._json_urls(v, out)
        elif isinstance(node, str):
            s = node.strip()
            if s.startswith(HOST) or (s.startswith("/") and not s.startswith("//") and " " not in s):
                out.append(s)

    def _text_urls(self, text, rel=False):
        text = html.unescape(text)
        out = []
        for m in ABS.finditer(text):
            if text[m.end():m.end() + 1] == "<" and text[m.end():m.end() + 2] != "</":
                continue  # documentation template such as /lang/<slug>/
            out.append(m.group(0).rstrip(".,:;"))
        if rel:
            for m in REL_TEXT.finditer(text):
                if text[m.end():m.end() + 1] == "<" and text[m.end():m.end() + 2] != "</":
                    continue  # template such as /repo/<owner>/<name>/
                out.append(m.group(0).rstrip(".,:;"))
        return [u for u in out if "<" not in u]

    def test_all(self):
        total = 0
        counts = {}
        for name, rel in (("sitemap.xml", False), ("llms.txt", True), ("feed.xml", False)):
            urls = self._text_urls((self.pub / name).read_text(encoding="utf-8"), rel)
            self.assertTrue(urls, name)
            counts[name] = self._check(name, urls)
        for name in ("stats.json", "today.json", "build.json"):
            out = []
            self._json_urls(json.loads((self.pub / name).read_text(encoding="utf-8")), out)
            counts[name] = self._check(name, out)
        out = []
        files = sorted((self.pub / "repo").glob("*/*/index.json"))
        self.assertTrue(files)
        for f in files:
            self._json_urls(json.loads(f.read_text(encoding="utf-8")), out)
        counts["repo/*/*/index.json"] = self._check("repo index.json", out)
        out = []
        pages = sorted(self.pub.rglob("*.html"))
        for f in pages:
            t = html.unescape(f.read_text(encoding="utf-8"))
            out += REL_ATTR.findall(t)
            out += [m.group(0) for m in ABS.finditer(t)]
        out = [u.rstrip(".,:;") for u in out]
        counts["html (%d pages)" % len(pages)] = self._check("html", out)
        total = sum(counts.values())
        print("\nemitted URLs checked:", total, counts)
        self.assertGreater(total, 1000)


if __name__ == "__main__":
    unittest.main()
