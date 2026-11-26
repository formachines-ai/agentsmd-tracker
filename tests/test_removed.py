"""Offline test: removals = present before + definite 404 now. Run: python3 -m unittest tests.test_removed"""
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build", ROOT / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

REPO = {"full_name": "o/n", "owner": "o", "name": "n", "language": "Python", "stars": 5, "default_branch": "main"}


def snap(**files):
    base = {s["path"]: {"present": False, "size": None, "definite": True} for s in build.PATHS}
    base.update(files)
    return {"status": "ok", "default_branch": "main", "files": base}


PRESENT = {"present": True, "size": 10}


class RemovedTest(unittest.TestCase):
    def test_present_to_404(self):
        a, r = build.diff_snapshots(REPO, snap(**{"AGENTS.md": PRESENT}), snap())
        self.assertEqual([x["path"] for x in r], ["AGENTS.md"])
        self.assertEqual((r[0]["owner"], r[0]["name"]), ("o", "n"))
        self.assertEqual(a, [])

    def test_present_to_network_error(self):
        new = snap(**{"AGENTS.md": {"present": None, "size": None}})
        self.assertEqual(build.diff_snapshots(REPO, snap(**{"AGENTS.md": PRESENT}), new), ([], []))

    def test_first_scan(self):
        self.assertEqual(build.diff_snapshots(REPO, None, snap()), ([], []))

    def test_absent_to_absent(self):
        self.assertEqual(build.diff_snapshots(REPO, snap(), snap()), ([], []))

    def test_carried_over(self):
        """run_scan with a failed attempt keeps the old snapshot: no removal. Uses a temp scan dir, no network."""
        import tempfile
        old = (build.SCAN_DIR, build.scan_repo)
        with tempfile.TemporaryDirectory() as t:
            build.SCAN_DIR = Path(t)
            try:
                build.write_json(build.scan_file_for(REPO), snap(**{"AGENTS.md": PRESENT}) | {"checked": "2026-11-14T04:00:00Z"})
                build.scan_repo = lambda repo, token: {"status": "error", "checked": "2026-11-15T04:00:00Z", "files": {}}
                st = build.run_scan([REPO], None, None, True)
                self.assertEqual(st["removed"], [])
                kept = build.read_json(build.scan_file_for(REPO), None)
                self.assertTrue(kept["files"]["AGENTS.md"]["present"])
            finally:
                build.SCAN_DIR, build.scan_repo = old

    def test_fixture_two_days(self):
        fx = ROOT / "tests" / "fixtures" / "removed"
        prev = json.loads((fx / "prev.json").read_text())
        new = json.loads((fx / "new.json").read_text())
        a, r = build.diff_snapshots(REPO, prev, new)
        self.assertEqual([(x["full_name"], x["path"]) for x in r], [("o/n", "AGENTS.md")])

    def test_removed_listed_unchecked_and_first_scan_not(self):
        """Three cases: removed path listed; repo not checked today (old snapshot kept, no new one) not listed; first scan not listed."""
        a, r = build.diff_snapshots(REPO, snap(**{"AGENTS.md": PRESENT}), snap())
        self.assertEqual(len(r), 1)
        self.assertEqual(build.diff_snapshots(REPO, snap(**{"AGENTS.md": PRESENT}), {"status": "error", "files": {}}), ([], []))
        self.assertEqual(build.diff_snapshots(REPO, None, snap()), ([], []))

    def test_published_links_and_feed(self):
        page = (ROOT / "public" / "index.html").read_text()
        self.assertIn("<h3>Removed in 24 h</h3>", page)
        sec = page.split('id="removed-24h">')[1].split("</p>")[0]
        if "none" not in sec:
            self.assertIn("?src=removed", sec)
        feed = (ROOT / "public" / "feed.xml").read_text()
        for t in re.findall(r"<title>(Removed:[^<]*)</title>", feed):
            self.assertTrue(t.startswith("Removed:"))

    def test_published(self):
        d = json.loads((ROOT / "public" / "today.json").read_text())
        self.assertIsInstance(d["removed"], list)
        self.assertEqual(d["removed_count"], len(d["removed"]))
        page = (ROOT / "public" / "index.html").read_text()
        m = re.search(r'id="removed-24h">Removed in 24 h on (\d{4}-\d\d-\d\d): (\d+)', page)
        self.assertTrue(m)
        self.assertEqual(m.group(1), d["generated"][:10])
        self.assertEqual(int(m.group(2)), d["removed_count"])
        self.assertIn("removed_count", (ROOT / "public" / "llms.txt").read_text())


if __name__ == "__main__":
    unittest.main()
