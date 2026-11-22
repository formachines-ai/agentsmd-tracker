"""Offline, read-only (T-0168): AI_POLICY.md and .github/AI_POLICY.md as presence+size paths.

20 fixture repos (including freeCodeCamp/freeCodeCamp) with mocked HEAD answers (no network, no sleeping, no token,
no writes to data/ or public/): scan_repo -> temp scan dir -> aggregate, compared with tests/fixtures/ai_policy/expected.json.
Sizes in the fixture are synthetic. Run: python3 -B -m unittest tests.test_ai_policy
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402

FX = ROOT / "tests" / "fixtures" / "ai_policy"
NEW = ("AI_POLICY.md", ".github/AI_POLICY.md")


class AiPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fx = json.loads((FX / "fixture.json").read_text())
        cls.exp = json.loads((FX / "expected.json").read_text())
        cls.repos = fx["repos"]
        cls.calls = []

        def fake_head(url, token=None):
            cls.calls.append(url)
            s, h = fx["heads"].get(url, [404, {}])
            return s, dict(h)

        cls.tmp = tempfile.TemporaryDirectory()
        scan_dir = Path(cls.tmp.name)
        cls.scans, cls.per_repo = {}, {}
        with mock.patch.object(build, "head", side_effect=fake_head), mock.patch.object(build.time, "sleep"), \
                mock.patch.object(build, "SCAN_DIR", scan_dir):
            for r in cls.repos:
                r = dict(r, full_name=f"{r['owner']}/{r['name']}")
                before = len(cls.calls)
                sc = build.scan_repo(r, None)
                cls.per_repo[r["full_name"]] = len(cls.calls) - before
                cls.scans[r["full_name"]] = sc
                (scan_dir / f"{r['owner']}__{r['name']}.json").write_text(json.dumps(sc))
            cls.agg = build.aggregate(cls.repos)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_paths_registered_as_files(self):
        kinds = {s["path"]: s["kind"] for s in build.PATHS}
        for p in NEW:
            self.assertEqual(kinds[p], "file")

    def test_twenty_repos_with_freecodecamp(self):
        self.assertEqual(len(self.repos), 20)
        self.assertIn("freeCodeCamp/freeCodeCamp", self.scans)

    def test_counts_and_by_language_match_fixture(self):
        self.assertEqual({p: self.agg["counts"][p] for p in NEW}, self.exp["counts"])
        got = {l: {"repos": v["repos"], **{p: v[p] for p in NEW}} for l, v in self.agg["by_lang"].items()}
        self.assertEqual(got, self.exp["by_language"])

    def test_sizes_presence_only(self):
        for name, sizes in self.exp["sizes"].items():
            for p, size in sizes.items():
                self.assertEqual(self.scans[name]["files"][p], {"present": True, "size": size})

    def test_head_only_no_content_requests(self):
        self.assertTrue(self.calls)
        for u in self.calls:   # one HEAD per URL, only raw file URLs or github.com repo/tree pages; never an API call
            self.assertTrue(u.startswith(("https://raw.githubusercontent.com/", "https://github.com/")), u)

    def test_requests_per_repo(self):
        n = len(build.PATHS)
        self.assertEqual(build.REQ_PER_REPO, n + 3)
        for name, sc in self.scans.items():
            any_present = any(f["present"] for f in sc["files"].values())
            want = n + 1 if any_present else n + 2   # T-0199: derived from PATHS (was fixture 11 / 12 for 10 paths)
            if not sc["files"].get(".clinerules", {}).get("present"):
                want += 1   # T-0233: .clinerules/ directory HEAD when the file is absent
            self.assertEqual(self.per_repo[name], want, name)

    def test_baseline_not_added(self):
        repo = dict(self.repos[0], full_name="freeCodeCamp/freeCodeCamp")
        new = self.scans["freeCodeCamp/freeCodeCamp"]
        old_files = {k: v for k, v in new["files"].items() if k not in NEW}   # snapshot from before the paths existed
        added, _ = build.diff_snapshots(repo, {"status": "ok", "files": old_files}, new)
        self.assertEqual([a for a in added if a["path"] in NEW], [])
        old_files.update({p: {"present": False, "size": None} for p in NEW})  # later scan: absent -> present is an add
        added, _ = build.diff_snapshots(repo, {"status": "ok", "files": old_files}, new)
        self.assertEqual(sorted(a["path"] for a in added if a["path"] in NEW), sorted(NEW))
        added, _ = build.diff_snapshots(repo, None, new)   # first scan of a repo
        self.assertEqual(added, [])

    def test_committed_stats_lists_both_paths(self):
        stats = json.loads((ROOT / "public" / "stats.json").read_text())
        for p in NEW:
            self.assertIn(p, stats["paths"])
            self.assertIn(p, stats["counts"])
            self.assertTrue(all(p in v for v in stats["by_language"].values()))
        self.assertEqual(len(stats["paths"]), len(build.PATHS))


if __name__ == "__main__":
    unittest.main()
