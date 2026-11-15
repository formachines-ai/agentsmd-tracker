"""Offline, read-only (T-0169): the method text agrees with PATHS and with build.json github_token.

Renders a temp copy of the site with GITHUB_TOKEN set and unset (build.py --no-scan, no network) and checks
public/index.html, public/llms.txt and public/build.json. Nothing is written to the checkout.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import build  # noqa: E402

DAY = "2026-11-15"


def render(token: bool) -> dict:
    t = Path(tempfile.mkdtemp(prefix="method-text-"))
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
    (t / "data" / "history" / f"{DAY}.json").write_text(json.dumps(
        {"date": DAY, "generated": DAY + "T05:30:00Z", "total": 1, "counts": {}, "any": 1, "by_language": {}, "added": [], "removed": []}))
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
    if token:
        env["GITHUB_TOKEN"] = "dummy-not-used"
    r = subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=t, capture_output=True, text=True, env=env)
    pub = t / "public"
    out = {"rc": r.returncode, "log": r.stderr + r.stdout, "tmp": t}
    for k, f in (("index", "index.html"), ("llms", "llms.txt"), ("build", "build.json")):
        out[k] = (pub / f).read_text() if (pub / f).exists() else ""
    return out


class MethodText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.on, cls.off = render(True), render(False)

    @classmethod
    def tearDownClass(cls):
        for r in (cls.on, cls.off):
            shutil.rmtree(r["tmp"], ignore_errors=True)

    def test_builds(self):
        for r in (self.on, self.off):
            self.assertEqual(r["rc"], 0, r["log"][-800:])

    def test_flag_in_build_json(self):
        self.assertIs(json.loads(self.on["build"])["github_token"], True)
        self.assertIs(json.loads(self.off["build"])["github_token"], False)

    def test_token_true(self):
        for k in ("index", "llms"):
            self.assertIn("optional GitHub token", self.on[k])
            self.assertNotIn("no token", self.on[k])

    def test_token_false(self):
        for k in ("index", "llms"):
            self.assertIn("one thread, no token", self.off[k])
            self.assertNotIn("optional GitHub token", self.off[k])

    def test_helpers(self):
        self.assertIn("no token", build.token_text(False))
        self.assertNotIn("no token", build.token_text(True))

    def test_paths_listed(self):
        self.assertEqual(len(build.PATHS), 10)
        for r in (self.on, self.off):
            for p in build.PATHS:
                name = p["path"] + ("/" if p["kind"] == "dir" else "")
                self.assertIn(name, r["index"])
                self.assertIn(name, r["llms"])
            self.assertIn(build.paths_text(), r["index"].replace("&#x27;", "'"))
            self.assertIn(build.paths_text(), r["llms"])
            self.assertEqual(json.loads(r["build"])["paths"], [p["path"] for p in build.PATHS])

    def test_no_hardcoded_eight(self):
        n = len(build.PATHS)
        for r in (self.on, self.off):
            for k in ("index", "llms"):
                self.assertIsNone(re.search(r"\b(8|eight) (tracked |fixed )?(file )?(paths|files|kinds|locations)", r[k]), k)
                self.assertIn(f"{n} path HEAD", r[k])


if __name__ == "__main__":
    unittest.main()
