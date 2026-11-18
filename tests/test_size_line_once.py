"""Offline, read-only (T-0197): the home page has one '>32 KiB' AGENTS.md sentence; its number is the stats.json bands gt_32k."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures" / "sizes"


class SizeLineOnce(unittest.TestCase):
    def test_once(self):
        t = Path(tempfile.mkdtemp(prefix="sizeonce-"))
        shutil.copy(REPO / "build.py", t / "build.py")
        shutil.copytree(REPO / "static", t / "static")
        shutil.copytree(FIX / "scan", t / "data" / "scan")
        shutil.copy(FIX / "repos.json", t / "data" / "repos.json")
        (t / "data" / "history").mkdir()
        (t / "public").mkdir()
        subprocess.run(["chmod", "-R", "u+w", str(t)], check=True)
        subprocess.run([sys.executable, "-B", "build.py", "--no-scan", "--now", "2026-11-15T06:00:00Z"],
                       cwd=t, check=True, capture_output=True)
        html = (t / "public" / "index.html").read_text()
        stats = json.loads((t / "public" / "stats.json").read_text())
        b = stats["sizes"]["AGENTS.md"]["bands"]
        self.assertEqual(html.count("larger than 32 KiB"), 1)
        self.assertEqual(html.count("AGENTS.md files in the sample are larger than 32 KiB"), 1)
        self.assertIn(f"{b['gt_32k']:,} of {sum(b.values()):,} AGENTS.md files in the sample are larger than 32 KiB", html)
        self.assertEqual(b["gt_32k"], stats["sizes"]["AGENTS.md"]["buckets"]["gt_32k"])
        self.assertNotIn("AGENTS.md</code> on", "".join(l for l in html.split("<li>") if "over 32768" in l))
        llms = (t / "public" / "llms.txt").read_text()
        self.assertIn("two size schemes", llms)
        self.assertIn("buckets", llms)
        self.assertIn("bands", llms)
        shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
