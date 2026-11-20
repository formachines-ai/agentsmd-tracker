"""Offline: build the real data/ with --no-scan into a temp dir, then assert on every generated page that
(a) each <a> to /go/ has rel containing nofollow, (b) each /go/**/index.html has noindex,nofollow meta,
(c) robots.txt keeps Disallow: /go/. Nothing is written to the checkout."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
A_TAG = re.compile(r"<a\b[^>]*>", re.I)
GO_HREF = re.compile(r'href="(?:https://agentsmd\.formachines\.ai)?/go/')
META = '<meta name="robots" content="noindex, nofollow">'


class GoBuildOffline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="gobuild-"))
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

    def test_links_nofollow(self):
        n, bad = 0, []
        for p in self.pub.rglob("*.html"):
            for tag in A_TAG.findall(p.read_text(encoding="utf-8")):
                if GO_HREF.search(tag):
                    n += 1
                    m = re.search(r'rel="([^"]*)"', tag)
                    if not m or "nofollow" not in m.group(1).split():
                        bad.append((str(p.relative_to(self.pub)), tag))
        self.assertGreater(n, 100)
        self.assertEqual(bad[:5], [], f"{len(bad)} of {n}")
        print(f"/go/ links checked: {n}")

    def test_go_pages_noindex(self):
        pages = sorted(self.pub.glob("go/**/index.html"))
        self.assertGreater(len(pages), 100)
        bad = [str(p.relative_to(self.pub)) for p in pages if META not in p.read_text(encoding="utf-8")]
        self.assertEqual(bad[:5], [])
        print(f"/go/ pages checked: {len(pages)}")

    def test_robots(self):
        lines = (self.pub / "robots.txt").read_text().splitlines()
        self.assertIn("Disallow: /go/", lines)


if __name__ == "__main__":
    unittest.main()
