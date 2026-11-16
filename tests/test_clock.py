"""Offline, read-only (T-0178): build.py takes one fixed clock (--now ISO or env BUILD_NOW).

One fixture is built twice in temp copies with the same --now while the real time (datetime.now) is patched to two
different dates: every output file must be byte-identical and today.json `generated` follows the fixed clock.
"""
import json
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
FIXED = "2026-11-20T04:00:00Z"
WRAP = """import sys, datetime as d, runpy
real = d.datetime.fromisoformat(sys.argv.pop(1))
class D(d.datetime):
    @classmethod
    def now(cls, tz=None):
        return real
d.datetime = D
sys.argv[0] = "build.py"
runpy.run_path("build.py", run_name="__main__")
"""


def build(real_now, extra, env_clock=None):
    t = Path(tempfile.mkdtemp(prefix="clock-"))
    shutil.copy(REPO / "build.py", t / "build.py")
    shutil.copytree(REPO / "static", t / "static")
    subprocess.run(["chmod", "-R", "u+w", str(t)], check=True)
    (t / "wrap.py").write_text(WRAP)
    (t / "data" / "scan").mkdir(parents=True)
    (t / "data" / "history").mkdir()
    (t / "public").mkdir()
    (t / "data" / "repos.json").write_text(json.dumps({"generated": SCAN, "query": {}, "repos": [
        {"id": 1, "full_name": "o/a", "owner": "o", "name": "a", "language": "Python", "stars": 9, "default_branch": "main"}]}))
    (t / "data" / "scan" / "o__a.json").write_text(json.dumps({"checked": SCAN, "status": "ok", "default_branch": "main",
                                                               "files": {"AGENTS.md": {"present": True, "size": 10}}}))
    (t / "data" / "history" / f"{DAY}.json").write_text(json.dumps({
        "date": DAY, "generated": SCAN, "sample": 1, "scanned": 1, "total": 1, "counts": {}, "any": 1, "by_language": {}, "added": [], "removed": []}))
    import os
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "BUILD_NOW")}
    if env_clock:
        env["BUILD_NOW"] = env_clock
    r = subprocess.run([sys.executable, "-B", "wrap.py", real_now, "--no-scan"] + extra, cwd=t, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr + r.stdout
    return t


def tree(t):
    return {str(p.relative_to(t / "public")): p.read_bytes() for p in sorted((t / "public").rglob("*")) if p.is_file()}


class Clock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = build("2026-12-01T10:00:00+00:00", ["--now", FIXED])
        cls.b = build("2027-03-09T23:59:59+00:00", ["--now", FIXED])
        cls.c = build("2027-03-09T23:59:59+00:00", [], env_clock=FIXED)

    @classmethod
    def tearDownClass(cls):
        for t in (cls.a, cls.b, cls.c):
            shutil.rmtree(t, ignore_errors=True)

    def test_byte_identical(self):
        fa, fb = tree(self.a), tree(self.b)
        self.assertGreater(len(fa), 5)
        self.assertEqual(sorted(fa), sorted(fb))
        for k in fa:
            self.assertEqual(fa[k], fb[k], k)

    def test_env_equals_flag(self):
        self.assertEqual(tree(self.a), tree(self.c))

    def test_built_at_follows_fixed_clock(self):
        b = json.loads((self.a / "public" / "build.json").read_text())
        self.assertEqual(b["built_at"], FIXED)
        self.assertEqual(b["build_seconds"], 0.0)

    def test_today_generated_follows_fixed_clock(self):
        # a scan-less build keeps the last real scan time; with a fixed clock that is the fixture's, never the patched real time
        for t in (self.a, self.b):
            today = json.loads((t / "public" / "today.json").read_text())
            self.assertEqual(today["generated"], SCAN)
            self.assertNotIn("2026-12-01", json.dumps(today))
            self.assertNotIn("2027-03", json.dumps(today))

    def test_scan_stamp_uses_fixed_clock(self):
        # a scan (here: a run whose history record is missing) stamps today's date from the fixed clock
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_clock", REPO / "build.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m._FIXED_NOW = m.parse_clock(FIXED)
        self.assertEqual(m.iso(m.now_utc()), FIXED)
        self.assertEqual(m.parse_clock("2026-11-20T04:00:00").isoformat(), "2026-11-20T04:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
