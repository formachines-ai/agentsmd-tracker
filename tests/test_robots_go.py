"""Offline: build with --no-scan into a temp dir; robots.txt disallows /go/ for all crawlers and keeps the
Sitemap line; sitemap.xml and llms.txt list no URL whose path starts with /go/ (/repo/golang/go/ and /lang/go/ are fine)."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GO_URL = re.compile(r"https?://[^/\s<\"')]+/go/")


class RobotsGo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="robotsgo-"))
        shutil.copy(REPO / "build.py", cls.tmp / "build.py")
        shutil.copytree(REPO / "static", cls.tmp / "static")
        shutil.copytree(REPO / "data", cls.tmp / "data")
        subprocess.run(["chmod", "-R", "u+w", str(cls.tmp)], check=True)
        (cls.tmp / "public").mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "BUILD_NOW")}
        r = subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=cls.tmp, capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr + r.stdout

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def read(self, name):
        return (self.tmp / "public" / name).read_text(encoding="utf-8")

    def test_robots(self):
        lines = self.read("robots.txt").splitlines()
        self.assertIn("User-agent: *", lines)
        group = lines[lines.index("User-agent: *") + 1:]
        group = group[:group.index("")] if "" in group else group
        self.assertIn("Disallow: /go/", group)
        for ok in ("/repo/", "/lang/", "/stats.json", "/today.json", "/feed.xml", "/llms.txt"):
            self.assertNotIn("Disallow: " + ok, lines)
        self.assertNotIn("Disallow: /", lines)
        self.assertTrue(any(l.startswith("Sitemap: ") and l.endswith("/sitemap.xml") for l in lines))

    def test_no_go_urls_listed(self):
        for name in ("sitemap.xml", "llms.txt"):
            self.assertEqual(GO_URL.findall(self.read(name)), [], name)


if __name__ == "__main__":
    unittest.main()
