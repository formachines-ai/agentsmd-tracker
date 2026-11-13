"""Offline, read-only test for METHOD_CHANGES: stats.json field, dated line on /, reason in today.json.
Run: python3 -m unittest tests.test_method_changes   (works under chmod -R a-w; writes nothing)
"""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build", ROOT / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class MethodChangesTest(unittest.TestCase):
    def test_first_entry(self):
        m = build.METHOD_CHANGES[0]
        self.assertEqual((m["date"], m["path"], m["commit"]), ("2026-11-13", ".cursor/rules", "6887ed8"))
        self.assertTrue(m["url"].endswith("/commit/6887ed8"))

    def test_stats_json(self):
        st = json.loads((ROOT / "public" / "stats.json").read_text())
        self.assertEqual(st["method_changes"], build.METHOD_CHANGES)

    def test_home_line(self):
        html = (ROOT / "public" / "index.html").read_text()
        self.assertIn("Method change 2026-11-13", html)
        self.assertIn('href="https://github.com/formachines-ai/agentsmd-tracker/commit/6887ed8"', html)

    def test_matching_removal_gets_reason(self):
        rem = [{"path": ".cursor/rules", "full_name": "a/b"}, {"path": "AGENTS.md", "full_name": "a/c"}]
        out = build.annotate_removed(rem, "2026-11-13")
        self.assertEqual(out[0]["reason"], "method_change")
        self.assertNotIn("reason", out[1])
        self.assertNotIn("reason", build.annotate_removed(rem, "2026-11-14")[0])

    def test_today_json_and_label(self):
        t = json.loads((ROOT / "public" / "today.json").read_text())
        html = (ROOT / "public" / "index.html").read_text()
        if t["date"] == "2026-11-13":
            cur = [x for x in t["removed"] if x["path"] == ".cursor/rules"]
            self.assertTrue(cur)
            self.assertTrue(all(x["reason"] == "method_change" for x in cur))
            self.assertIn("no longer detected after the 2026-11-13 method change", html)


if __name__ == "__main__":
    unittest.main()
