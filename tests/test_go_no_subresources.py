"""Offline: build with --no-scan into a temp dir; every /go/**/index.html (redirect, vote, github, telegram) must
carry no same-site subresource (icon, stylesheet, img, script), keep the redirect and the robots meta."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
META = '<meta name="robots" content="noindex, nofollow">'
FORBIDDEN = re.compile(r"<(link|img|script|style|iframe|source|video|audio|object|embed)\b|url\(|favicon|style\.css", re.I)
REFRESH = re.compile(r'<meta http-equiv="refresh" content="0; url=([^"]+)">')


class GoNoSubresources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="gosub-"))
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

    def test_go_pages(self):
        pages = sorted((self.pub / "go").rglob("index.html"))
        self.assertGreater(len(pages), 100)
        bad, gh = [], 0
        for p in pages:
            h = p.read_text(encoding="utf-8")
            rel = str(p.relative_to(self.pub))
            m = FORBIDDEN.search(h)
            if m:
                bad.append((rel, "subresource " + m.group(0)))
            if META not in h:
                bad.append((rel, "robots meta"))
            t = REFRESH.search(h)
            if not t:
                bad.append((rel, "no refresh"))
                continue
            tgt = t.group(1).replace("&amp;", "&")
            if f'href="{t.group(1)}"' not in h:
                bad.append((rel, "no fallback link"))
            if rel.startswith("go/vote/"):
                if not tgt.startswith("/repo/"):
                    bad.append((rel, tgt))
            elif tgt.startswith("https://github.com/") or tgt.startswith("https://raw.githubusercontent.com/") or tgt.startswith("https://t.me/"):
                gh += 1
            else:
                bad.append((rel, tgt))
        self.assertEqual(bad[:5], [], f"{len(bad)} problems")
        print(f"/go/ pages checked: {len(pages)}, external targets: {gh}")


if __name__ == "__main__":
    unittest.main()
