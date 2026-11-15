"""Offline, read-only: recompute sizes buckets of AGENTS.md / CLAUDE.md from data/scan and compare with public/stats.json."""
import json
import statistics
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class SizeBuckets(unittest.TestCase):
    def test_sizes_match_scan(self):
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
            vals.sort()
            q1, q2, q3 = statistics.quantiles(vals, n=4, method="inclusive")
            s = stats["sizes"][path]
            self.assertEqual(s["n"], len(vals))
            self.assertEqual(s["unknown"], unknown)
            self.assertEqual((s["p25"], s["median"], s["p75"]), (round(q1), round(q2), round(q3)))
            b = s["buckets"]
            self.assertEqual(b, {"lt_2k": sum(v < 2048 for v in vals), "2k_8k": sum(2048 <= v < 8192 for v in vals),
                                 "8k_32k": sum(8192 <= v <= 32768 for v in vals), "gt_32k": sum(v > 32768 for v in vals)})
            self.assertEqual(sum(b.values()), s["n"])


if __name__ == "__main__":
    unittest.main()
