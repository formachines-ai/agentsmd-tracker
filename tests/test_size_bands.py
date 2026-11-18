"""Offline, read-only: stats.json sizes.<type>.bands (KiB bands) recomputed from data/scan; sum equals present count; home line matches."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class SizeBands(unittest.TestCase):
    def test_bands(self):
        stats = json.loads((ROOT / "public" / "stats.json").read_text())
        repos = json.loads((ROOT / "data" / "repos.json").read_text())["repos"]
        for path in ("AGENTS.md", "CLAUDE.md"):
            vals, unknown = [], 0
            for r in repos:
                f = ROOT / "data" / "scan" / f"{r['owner']}__{r['name']}.json"
                if not f.exists():
                    continue
                d = json.loads(f.read_text())
                if d.get("status") != "ok":
                    continue
                e = d.get("files", {}).get(path, {})
                if e.get("present"):
                    if isinstance(e.get("size"), int) and e["size"] >= 0:
                        vals.append(e["size"])
                    else:
                        unknown += 1
            b = stats["sizes"][path]["bands"]
            self.assertEqual(b, {"lt_1k": sum(v < 1024 for v in vals), "1k_4k": sum(1024 <= v < 4096 for v in vals),
                                 "4k_16k": sum(4096 <= v < 16384 for v in vals), "16k_32k": sum(16384 <= v <= 32768 for v in vals),
                                 "gt_32k": sum(v > 32768 for v in vals), "unknown": unknown})
            self.assertEqual(sum(b.values()), len(vals) + unknown)
            self.assertEqual(sum(b.values()), stats["counts"][path] if "counts" in stats and isinstance(stats["counts"].get(path), int) else sum(b.values()))
        html = (ROOT / "public" / "index.html").read_text()
        k = stats["sizes"]["AGENTS.md"]["bands"]["gt_32k"]
        n = sum(stats["sizes"]["AGENTS.md"]["bands"].values())
        self.assertIn(f"{k:,} of {n:,} AGENTS.md files in the sample are larger than 32 KiB", html)
        self.assertIn("bands", (ROOT / "public" / "llms.txt").read_text())


if __name__ == "__main__":
    unittest.main()
