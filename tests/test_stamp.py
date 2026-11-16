"""Offline, read-only (T-0171): footer 'updated' and JSON-LD dates are the latest scan time, not the build clock.

Two temp-copy builds (--no-scan) from the same scan data with different build clocks (build.py --now) must give byte-identical HTML; the footer equals the scan time. No scan record -> build time.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent
DAY = "2026-11-15"
SCAN = DAY + "T05:30:07Z"

def build(clock: str, record: bool = True) -> Path:
    t = Path(tempfile.mkdtemp(prefix="stamp-"))
    shutil.copy(REPO / "build.py", t / "build.py")
    shutil.copytree(REPO / "static", t / "static")
    subprocess.run(["chmod", "-R", "u+w", str(t)], check=True)
    (t / "data" / "scan").mkdir(parents=True)
    (t / "data" / "history").mkdir()
    (t / "public").mkdir()
    (t / "data" / "repos.json").write_text(json.dumps({"generated": SCAN, "query": {}, "repos": [
        {"id": 1, "full_name": "o/a", "owner": "o", "name": "a", "language": "Python", "stars": 9, "default_branch": "main"}]}))
    (t / "data" / "scan" / "o__a.json").write_text(json.dumps({"checked": SCAN, "status": "ok", "default_branch": "main",
                                                               "files": {"AGENTS.md": {"present": True, "size": 10}}}))
    if record:
        (t / "data" / "history" / f"{DAY}.json").write_text(json.dumps({
            "date": DAY, "generated": SCAN, "sample": 1, "scanned": 1, "total": 1, "counts": {}, "any": 1, "by_language": {}, "added": [], "removed": []}))
    r = subprocess.run([sys.executable, "-B", "build.py", "--no-scan", "--now", clock], cwd=t, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    return t


def htmls(t: Path) -> dict:
    return {str(p.relative_to(t / "public")): p.read_bytes() for p in sorted((t / "public").rglob("*.html"))}


class Stamp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = build(DAY + "T12:00:00+00:00")
        cls.b = build(DAY + "T18:45:10+00:00")
        cls.n = build(DAY + "T12:00:00+00:00", record=False)

    @classmethod
    def tearDownClass(cls):
        for t in (cls.a, cls.b, cls.n):
            shutil.rmtree(t, ignore_errors=True)

    def test_html_identical_across_build_clocks(self):
        ha, hb = htmls(self.a), htmls(self.b)
        self.assertTrue(ha)
        self.assertEqual(ha.keys(), hb.keys())
        for k in ha:
            self.assertEqual(ha[k], hb[k], k)

    def test_footer_and_jsonld_are_scan_time(self):
        for t in (self.a, self.b):
            html = (t / "public" / "index.html").read_text()
            self.assertIn("updated " + SCAN + "</p>", html)
            self.assertIn("Built by AI agents (agent-team) without human editing", html)
            self.assertNotIn("T12:00:00Z", html)
            self.assertNotIn("T18:45:10Z", html)
            self.assertTrue(re.search(r'"dateModified": ?"' + SCAN + '"', html))
            card = (t / "public" / "repo" / "o" / "a" / "index.html").read_text()
            self.assertIn("updated " + SCAN + "</p>", card)

    def test_build_json_keeps_real_build_time(self):
        ba = json.loads((self.a / "public" / "build.json").read_text())
        bb = json.loads((self.b / "public" / "build.json").read_text())
        self.assertEqual(ba["built_at"], DAY + "T12:00:00Z")
        self.assertEqual(bb["built_at"], DAY + "T18:45:10Z")
        self.assertEqual(ba["scan"]["generated"], SCAN)
        self.assertFalse(ba["data_delayed"])

    def test_only_build_json_built_at_differs(self):
        def files(t):
            return {str(p.relative_to(t / "public")): p.read_bytes() for p in sorted((t / "public").rglob("*")) if p.is_file()}
        fa, fb = files(self.a), files(self.b)
        self.assertEqual(fa.keys(), fb.keys())
        for k in fa:
            if k != "build.json":
                self.assertEqual(fa[k], fb[k], k)
        ba, bb = json.loads(fa["build.json"]), json.loads(fb["build.json"])
        self.assertEqual({k for k in ba.keys() | bb.keys() if ba.get(k) != bb.get(k)}, {"built_at"})
        self.assertIn("<lastBuildDate>Sun, 15 Nov 2026 05:30:07 +0000</lastBuildDate>", fa["feed.xml"].decode())
        llms = fa["llms.txt"].decode()
        self.assertIn("Data scanned at: " + SCAN, llms)
        self.assertNotIn("Site built at", llms)
        self.assertNotIn(ba["built_at"], llms)

    def test_same_dir_rebuild_changes_only_built_at(self):
        t = self.a
        snap = {str(p.relative_to(t)): p.read_bytes() for p in sorted((t / "public").rglob("*")) if p.is_file()}
        r = subprocess.run([sys.executable, "-B", "build.py", "--no-scan", "--now", DAY + "T23:00:00+00:00"], cwd=t, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        after = {str(p.relative_to(t)): p.read_bytes() for p in sorted((t / "public").rglob("*")) if p.is_file()}
        self.assertEqual(snap.keys(), after.keys())
        self.assertEqual([k for k in snap if snap[k] != after[k]], ["public/build.json"])
        old, new = json.loads(snap["public/build.json"]), json.loads(after["public/build.json"])
        self.assertEqual(new["built_at"], DAY + "T23:00:00Z")
        self.assertEqual({k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}, {"built_at"})

    def test_no_record_falls_back_to_build_time(self):
        html = (self.n / "public" / "index.html").read_text()
        self.assertIn("updated " + DAY + "T12:00:00Z</p>", html)


if __name__ == "__main__":
    unittest.main()
