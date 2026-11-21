"""T-0224: the home page has a dated plain-text sentence, a Dataset JSON-LD and a meta description whose numbers equal stats.json.
Offline: builds a temp copy of the repo with --no-scan."""
import html, json, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class HomeDated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = Path(tempfile.mkdtemp(prefix="t0224-"))
        for n in ("data", "static", "public"):
            shutil.copytree(REPO / n, cls.t / n)
        shutil.copy(REPO / "build.py", cls.t / "build.py")
        r = subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=cls.t, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        cls.html = (cls.t / "public" / "index.html").read_text(encoding="utf-8")
        cls.st = json.loads((cls.t / "public" / "stats.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.t, ignore_errors=True)

    def test_paragraph(self):
        m = re.search(r'<p id="dated-counts">(.*?)</p>', self.html, re.S)
        self.assertTrue(m)
        txt = html.unescape(m.group(1))
        st = self.st
        M = st["denominator"]["M"]
        self.assertTrue(txt.startswith("On " + st["generated"][:10]))
        for p in ("AGENTS.md", "CLAUDE.md", "llms.txt"):
            n = st["counts"][p]
            self.assertIn(f"{n:,} of {M:,} (", txt)
            self.assertIn(f"have {p}", txt)

    def test_jsonld_and_meta(self):
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', self.html, re.S)
        self.assertEqual(len(blocks), 1)
        d = json.loads(blocks[0])
        self.assertEqual(d["@type"], "Dataset")
        self.assertEqual(d["dateModified"], self.st["generated"])
        self.assertEqual(d["license"], "https://creativecommons.org/licenses/by/4.0/")
        urls = {x["contentUrl"] for x in d["distribution"]}
        self.assertTrue({self.st["site"] + "/stats.json", self.st["site"] + "/today.json"} <= urls)
        desc = html.unescape(re.search(r'<meta name="description" content="([^"]*)"', self.html).group(1))
        self.assertIn(f"{self.st['counts']['AGENTS.md']:,} of", desc)
        self.assertIn(self.st["generated"][:10], desc)


if __name__ == "__main__":
    unittest.main()
