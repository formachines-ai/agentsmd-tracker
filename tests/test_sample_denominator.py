"""Offline (T-0212): M + excluded = sample size, excluded repos keep a card with status, the sample never shrinks.

Builds a temp copy of the repository with --no-scan; nothing is written to the checkout."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent


class SampleDenominator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="denom-"))
        shutil.copy(REPO / "build.py", cls.tmp / "build.py")
        shutil.copytree(REPO / "static", cls.tmp / "static")
        shutil.copytree(REPO / "data", cls.tmp / "data")
        (cls.tmp / "public").mkdir()
        subprocess.run(["chmod", "-R", "u+w", str(cls.tmp)], check=True)
        subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=cls.tmp, check=True, capture_output=True)
        cls.pub = cls.tmp / "public"
        cls.stats = json.loads((cls.pub / "stats.json").read_text())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_m_plus_excluded_is_sample(self):
        d = self.stats["denominator"]
        self.assertEqual(d["M"] + d["excluded"], d["sample_size"])
        self.assertEqual(d["sample_size"], self.stats["sample_size"])
        self.assertEqual(d["M"], self.stats["scanned"])
        self.assertEqual(sum(d["excluded_by_reason"].values()), d["excluded"])
        self.assertEqual(len(d["excluded_repos"]), d["excluded"])
        for key in ("moved", "deleted", "archived", "fork", "unreachable"):
            self.assertIn(key, d["excluded_by_reason"])
        self.assertRegex(d["date"], r"^\d{4}-\d\d-\d\d$")

    def test_existing_keys_kept(self):
        for k in ("sample", "sample_size", "scanned", "pending", "unreachable", "counts", "history"):
            self.assertIn(k, self.stats)

    def test_excluded_repo_has_card_with_status(self):
        items = self.stats["denominator"]["excluded_repos"]
        for it in items:
            owner, name = it["repo"].split("/")
            html = (self.pub / "repo" / owner / name / "index.html").read_text()
            self.assertIn(f"Status: {it['status']}", html)
            self.assertIn("First seen in the sample on", html)
            idx = json.loads((self.pub / "repo" / owner / name / "index.json").read_text())
            self.assertEqual(idx["status"], "unreachable")

    def test_llms_txt_defines_m(self):
        txt = (self.pub / "llms.txt").read_text()
        self.assertIn("Denominator: M =", txt)
        self.assertIn("excluded =", txt)

    def test_no_repo_leaves_the_sample(self):
        repos = {r["full_name"] for r in json.loads((REPO / "data" / "repos.json").read_text())["repos"]}
        hist = [json.loads(p.read_text()) for p in sorted((REPO / "data" / "history").glob("*.json"))]
        samples = [h["sample"] for h in hist]
        self.assertEqual(samples, sorted(samples), "sample shrank between snapshots")
        self.assertGreaterEqual(len(repos), samples[-1])
        for p in (REPO / "data" / "scan").glob("*.json"):
            self.assertIn(p.stem.replace("__", "/", 1), repos)


class ExcludedSince(unittest.TestCase):
    """T-0213: excluded_since / excluded_since_source; offline, temp copy, no network."""

    def _build(self, tmp):
        shutil.copy(REPO / "build.py", tmp / "build.py")
        shutil.copytree(REPO / "static", tmp / "static")
        shutil.copytree(REPO / "data", tmp / "data")
        (tmp / "public").mkdir()
        subprocess.run(["chmod", "-R", "u+w", str(tmp)], check=True)

    def _run(self, tmp):
        subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=tmp, check=True, capture_output=True)
        return json.loads((tmp / "public" / "stats.json").read_text())["denominator"]["excluded_repos"]

    def test_live_entries_have_valid_fields(self):
        import datetime
        for it in json.loads((REPO / "public" / "stats.json").read_text())["denominator"]["excluded_repos"]:
            self.assertIn(it["excluded_since_source"], ("observed", "inferred_from_history", "unknown"))
            if it["excluded_since_source"] == "unknown":
                self.assertIsNone(it["excluded_since"])
            else:
                datetime.date.fromisoformat(it["excluded_since"])

    def test_observed_inferred_and_kept_on_rebuild(self):
        tmp = Path(tempfile.mkdtemp(prefix="exsince-"))
        try:
            self._build(tmp)
            first = {i["repo"]: i for i in self._run(tmp)}
            self.assertTrue(first)
            for it in first.values():                       # inferred (backfilled from history) or unknown, never observed
                self.assertIn(it["excluded_since_source"], ("inferred_from_history", "unknown"))
            # observed: a repo that was ok in the previous snapshot leaves M in the scan of 2026-11-20
            sys.path.insert(0, str(tmp))
            try:
                import importlib
                b = importlib.import_module("build")
            finally:
                sys.path.remove(str(tmp))
            new = {"status": "unreachable", "checked": "2026-11-20T04:00:00Z"}
            b.merge_excluded({"status": "ok"}, new)
            self.assertEqual((new["excluded_since"], new["excluded_since_source"]), ("2026-11-20", "observed"))
            again = {"status": "unreachable", "checked": "2026-11-21T04:00:00Z"}
            b.merge_excluded(new, again)                    # date kept on a later scan
            self.assertEqual((again["excluded_since"], again["excluded_since_source"]), ("2026-11-20", "observed"))
            back = {"status": "ok", "checked": "2026-11-22T04:00:00Z"}
            b.merge_excluded(again, back)
            self.assertNotIn("excluded_since", back)
            first_scan = {"status": "unreachable", "checked": "2026-11-20T04:00:00Z"}
            b.merge_excluded(None, first_scan)              # first scan outside M: no observed date
            self.assertNotIn("excluded_since", first_scan)
            # inference: counts 0,1,1,3 -> slots 11-13, 11-18, 11-18; moved_detected bounds the moved ones; ambiguity -> None
            h = [{"date": d, "unreachable": n} for d, n in (("2026-11-10", 0), ("2026-11-13", 1), ("2026-11-18", 3))]
            self.assertEqual(b.infer_excluded_dates(h, 3, [], ["2026-11-18", "2026-11-15", None]), ["2026-11-18", "2026-11-18", "2026-11-13"])
            self.assertEqual(b.infer_excluded_dates(h, 3, [], [None, None, None]), [None, None, None])
            self.assertEqual(b.infer_excluded_dates(h, 4, [], [None] * 4), [None] * 4)   # history never reached 4
            h0 = [{"date": "2026-11-10", "unreachable": 1}]
            self.assertEqual(b.infer_excluded_dates(h0, 1, [], [None]), [None])         # first day is a baseline
            # rebuild keeps the stored date: edit the cache to a distinct observed date, rebuild, still there
            name = next(iter(first)).replace("/", "__")
            f = tmp / "data" / "scan" / f"{name}.json"
            sc = json.loads(f.read_text())
            sc["excluded_since"], sc["excluded_since_source"] = "2026-11-16", "observed"
            f.write_text(json.dumps(sc))
            kept = {i["repo"]: i for i in self._run(tmp)}[next(iter(first))]
            self.assertEqual((kept["excluded_since"], kept["excluded_since_source"]), ("2026-11-16", "observed"))
            owner, rname = next(iter(first)).split("/")
            html = (tmp / "public" / "repo" / owner / rname / "index.html").read_text()
            self.assertIn("excluded since 2026-11-16 (observed", html)
            idx = json.loads((tmp / "public" / "repo" / owner / rname / "index.json").read_text())
            self.assertEqual(idx["excluded_since"], "2026-11-16")
            self.assertIn("excluded_since_source", (tmp / "public" / "llms.txt").read_text())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
