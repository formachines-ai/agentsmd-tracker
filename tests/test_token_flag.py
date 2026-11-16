"""Offline, read-only (T-0170): build.json github_token and the method sentence come from the latest scan's record.

Builds temp copies with build.py --no-scan (no network): record true + no env token, record false + env token,
no record (falls back to the environment, github_token_source 'env'). Nothing is written to the checkout.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent
DAY = "2026-11-15"


def render(record, env_token: bool) -> dict:
    t = Path(tempfile.mkdtemp(prefix="token-flag-"))
    shutil.copy(REPO / "build.py", t / "build.py")
    shutil.copytree(REPO / "static", t / "static")
    subprocess.run(["chmod", "-R", "u+w", str(t)], check=True)
    (t / "data" / "scan").mkdir(parents=True)
    (t / "data" / "history").mkdir()
    (t / "public").mkdir()
    (t / "data" / "repos.json").write_text(json.dumps({"generated": DAY + "T05:00:00Z", "query": {}, "repos": [
        {"id": 1, "full_name": "o/a", "owner": "o", "name": "a", "language": "Python", "stars": 9, "default_branch": "main"}]}))
    (t / "data" / "scan" / "o__a.json").write_text(json.dumps({"checked": DAY + "T05:00:00Z", "status": "ok", "default_branch": "main",
                                                               "files": {"AGENTS.md": {"present": True, "size": 10}}}))
    hist = {"date": DAY, "generated": DAY + "T05:30:00Z", "total": 1, "scanned": 1, "counts": {}, "any": 1, "by_language": {}, "added": [], "removed": []}
    if record is not None:
        hist["github_token"] = record
    (t / "data" / "history" / f"{DAY}.json").write_text(json.dumps(hist))
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
    if env_token:
        env["GITHUB_TOKEN"] = "dummy-not-used"
    r = subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=t, capture_output=True, text=True, env=env)
    pub = t / "public"
    out = {"rc": r.returncode, "log": r.stderr + r.stdout, "tmp": t}
    for k, f in (("index", "index.html"), ("llms", "llms.txt"), ("build", "build.json")):
        out[k] = (pub / f).read_text() if (pub / f).exists() else ""
    out["bj"] = json.loads(out["build"]) if out["build"] else {}
    return out


class TokenFlag(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rec_true = render(True, False)
        cls.rec_false = render(False, True)
        cls.none_off = render(None, False)
        cls.none_on = render(None, True)

    @classmethod
    def tearDownClass(cls):
        for r in (cls.rec_true, cls.rec_false, cls.none_off, cls.none_on):
            shutil.rmtree(r["tmp"], ignore_errors=True)

    def check(self, r, flag, source):
        self.assertEqual(r["rc"], 0, r["log"][-800:])
        self.assertIs(r["bj"]["github_token"], flag)
        self.assertEqual(r["bj"]["github_token_source"], source)
        for k in ("index", "llms"):
            if flag:
                self.assertIn("optional GitHub token", r[k])
                self.assertNotIn("no token", r[k])
            else:
                self.assertIn("one thread, no token", r[k])
                self.assertNotIn("optional GitHub token", r[k])
        self.assertNotIn("dummy-not-used", r["build"] + r["index"] + r["llms"])

    def test_record_true_no_env_token(self):
        self.check(self.rec_true, True, "scan")

    def test_record_false_with_env_token(self):
        self.check(self.rec_false, False, "scan")

    def test_no_record_falls_back_to_env(self):
        self.check(self.none_off, False, "env")
        self.check(self.none_on, True, "env")


if __name__ == "__main__":
    unittest.main()
