"""Offline (T-0255): data_delayed is true (and the 'Data delayed' note is on /) when the newest scan UTC day is earlier than the build day; false when equal."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent


class DataDelayed(unittest.TestCase):
    def build(self, now):
        tmp = Path(tempfile.mkdtemp(prefix="delayed-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy(REPO / "build.py", tmp / "build.py")
        shutil.copytree(REPO / "static", tmp / "static")
        shutil.copytree(REPO / "data", tmp / "data")
        (tmp / "public").mkdir()
        subprocess.run(["chmod", "-R", "u+w", str(tmp)], check=True)
        subprocess.run([sys.executable, "-B", "build.py", "--no-scan", "--now", now], cwd=tmp, check=True, capture_output=True)
        return json.loads((tmp / "public/build.json").read_text()), (tmp / "public/index.html").read_text()

    def scan_day(self):
        return sorted((REPO / "data/history").glob("*.json"))[-1].stem

    def test_yesterday_scan_is_delayed(self):
        from datetime import date, timedelta
        d = date.fromisoformat(self.scan_day()) + timedelta(days=1)
        b, h = self.build(f"{d}T06:00:00Z")
        self.assertTrue(b["data_delayed"], b["delay_reason"])
        self.assertIn("Data delayed.", h)

    def test_today_scan_is_not_delayed(self):
        b, h = self.build(f"{self.scan_day()}T23:00:00Z")
        self.assertFalse(b["data_delayed"])
        self.assertNotIn("Data delayed.", h)


if __name__ == "__main__":
    unittest.main()
