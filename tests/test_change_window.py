"""Offline (T-0258): stats.json change_7d_window matches the history rows behind change_7d_pp; llms.txt defines sizes once."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent


class ChangeWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = Path(tempfile.mkdtemp(prefix="window-"))
        cls.addClassCleanup(shutil.rmtree, tmp, True)
        shutil.copy(REPO / "build.py", tmp / "build.py")
        shutil.copytree(REPO / "static", tmp / "static")
        shutil.copytree(REPO / "data", tmp / "data")
        (tmp / "public").mkdir()
        subprocess.run(["chmod", "-R", "u+w", str(tmp)], check=True)
        subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=tmp, check=True, capture_output=True)
        cls.stats = json.loads((tmp / "public/stats.json").read_text())
        cls.llms = (tmp / "public/llms.txt").read_text()

    def test_window_matches_history(self):
        s = self.stats
        w = s["change_7d_window"]
        self.assertEqual(set(w), {"from", "to", "M_from", "M_to"})
        self.assertIsNotNone(w["from"])
        rows = {h["date"]: h for h in s["history"]}
        self.assertEqual(w["to"], s["history"][-1]["date"])
        self.assertIn(w["from"], rows)
        self.assertEqual(w["M_from"], rows[w["from"]]["scanned"])
        self.assertEqual(w["M_to"], rows[w["to"]]["scanned"])
        self.assertIsInstance(w["M_from"], int)
        self.assertIsInstance(w["M_to"], int)
        from datetime import date
        self.assertEqual((date.fromisoformat(w["to"]) - date.fromisoformat(w["from"])).days, 7)
        self.assertIsNotNone(s["change_7d_pp"]["AGENTS.md"])

    def test_llms_defines_sizes_once(self):
        defs = [l for l in self.llms.splitlines() if l.startswith("- sizes in stats.json")]
        self.assertEqual(len(defs), 1, defs)
        self.assertIn("change_7d_window", self.llms)


if __name__ == "__main__":
    unittest.main()
