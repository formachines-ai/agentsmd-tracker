"""Offline VISION promises, checked against the real build.py running in a temp copy of the committed snapshot:
 (a) a failed scan keeps the last good snapshot, marked data_delayed, never zeros;
 (b) a repo that is gone/moved keeps its /repo/ card and index.json and shows a status.
No network (a sitecustomize replaces http.client.HTTPSConnection), no writes to the checkout (temp dir only)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

FAKE_NET = '''
import http.client, os
MODE = os.environ["FAKE_NET_MODE"]   # "fail" = connection error; "404" = 404 everywhere;
                                     # "301" = file/tree URLs 404, the bare github.com/<owner>/<name> URL answers 301 (moved)
class _Resp:
    def __init__(s, st): s.status = st
    def read(s): return b""
    def getheaders(s): return []
class _Conn:
    def __init__(s, host, timeout=None): s.host = host
    def request(s, method, path, headers=None):
        if MODE == "fail": raise OSError("fake: network down")
        s.st = 404
        if MODE == "301" and s.host == "github.com" and path.strip("/").count("/") == 1: s.st = 301
    def getresponse(s): return _Resp(s.st)
    def close(s): pass
http.client.HTTPSConnection = _Conn
'''


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build(mode, age_hours, target=None):
    """Copy build.py + static + data into a temp dir, age the snapshot, run the real build there. Returns (tmp, log)."""
    tmp = Path(tempfile.mkdtemp(prefix="fallback-"))
    shutil.copy(REPO / "build.py", tmp / "build.py")
    shutil.copytree(REPO / "static", tmp / "static")
    shutil.copytree(REPO / "data", tmp / "data")
    shutil.copytree(REPO / "public", tmp / "public")
    for q in [tmp, *tmp.rglob("*")]:      # the checkout may be read-only (chmod -R a-w): the copies must be writable
        q.chmod(q.stat().st_mode | 0o200)
    (tmp / "net").mkdir()
    (tmp / "net" / "sitecustomize.py").write_text(FAKE_NET)
    now = datetime.now(timezone.utc)
    for f in (tmp / "data" / "scan").glob("*.json"):
        d = json.loads(f.read_text())
        if target and f.name == target.replace("/", "__") + ".json":
            d["checked"] = iso(now - timedelta(hours=30))      # the only repo that is due for a rescan
        else:
            d["checked"] = iso(now - timedelta(hours=age_hours))
        f.write_text(json.dumps(d))
    last = sorted((tmp / "data" / "history").glob("*.json"))[-1]
    h = json.loads(last.read_text())
    h["generated"] = iso(now - timedelta(hours=age_hours))
    last.write_text(json.dumps(h))
    env = dict(os.environ, PYTHONPATH=str(tmp / "net"), FAKE_NET_MODE=mode)
    env.pop("GITHUB_TOKEN", None)
    args = [sys.executable, str(tmp / "build.py"), "--pause", "0"] + (["--limit", "1"] if target else [])
    p = subprocess.run(args, cwd=tmp, env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-2000:]
    return tmp, p.stderr


class FailedScan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = json.loads((REPO / "public" / "stats.json").read_text())
        # every HEAD fails; the snapshot is 48 h old, i.e. beyond the 36 h freshness limit
        cls.tmp, cls.log = build("fail", age_hours=48)
        cls.pub = cls.tmp / "public"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_build_json_data_delayed(self):
        b = json.loads((self.pub / "build.json").read_text())
        self.assertTrue(b["data_delayed"])
        self.assertTrue(b["delay_reason"])
        self.assertEqual(b["scanned_ok"], self.before["scanned"])      # last good snapshot still counted
        self.assertGreater(b["scanned_ok"], 0)
        print(f"build.json: data_delayed={b['data_delayed']} scanned_ok={b['scanned_ok']} reason={b['delay_reason']!r}")

    def test_stats_json_keeps_last_good_counts(self):
        s = json.loads((self.pub / "stats.json").read_text())
        self.assertTrue(s["data_delayed"])
        self.assertEqual(s["counts"], self.before["counts"])
        self.assertEqual(s["any"], self.before["any"])
        self.assertEqual(s["scanned"], self.before["scanned"])
        self.assertGreater(s["counts"]["AGENTS.md"], 0)
        self.assertGreater(s["any"], 0)
        print(f"stats.json: AGENTS.md={s['counts']['AGENTS.md']} any={s['any']} scanned={s['scanned']} (unchanged, not 0)")

    def test_home_shows_note_and_numbers(self):
        html = (self.pub / "index.html").read_text()
        self.assertIn("Data delayed.", html)
        self.assertIn("last successful scan", html)
        n, total = self.before["counts"]["AGENTS.md"], self.before["scanned"]
        self.assertIn(f"{n:,} of {total:,}", html)
        self.assertNotIn("0 of 0", html)
        print(f"/: 'Data delayed.' banner present, '{n:,} of {total:,}' still shown")


class GoneRepo(unittest.TestCase):
    TARGET = "0x192/universal-android-debloater"

    def check(self, mode):
        tmp, log = build(mode, age_hours=1, target=self.TARGET)
        try:
            o, n = self.TARGET.split("/")
            self.assertIn(f"{self.TARGET} (", log)                       # the scan really hit this repo
            card = tmp / "public" / "repo" / o / n
            self.assertTrue((card / "index.html").is_file(), "card removed")
            self.assertTrue((card / "index.json").is_file(), "index.json removed")
            j = json.loads((card / "index.json").read_text())
            self.assertEqual(j["repo"], self.TARGET)
            self.assertEqual(j["status"], "unreachable")
            self.assertIn("Scan status: unreachable", (card / "index.html").read_text())
            b = json.loads((tmp / "public" / "build.json").read_text())
            self.assertEqual(b["unreachable"], 1)
            print(f"HTTP {mode} for {self.TARGET}: card + index.json kept, status={j['status']}, build.json unreachable={b['unreachable']}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_404(self):
        self.check("404")

    def test_moved_301(self):
        self.check("301")


if __name__ == "__main__":
    unittest.main(verbosity=2)
