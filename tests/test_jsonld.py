"""Home page carries exactly one JSON-LD Dataset block that matches the committed stats.json. Offline, read-only."""
import json, re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUB = ROOT / "public"
BLOCK = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


class JsonLd(unittest.TestCase):
    def setUp(self):
        self.html = (PUB / "index.html").read_text(encoding="utf-8")
        self.stats = json.loads((PUB / "stats.json").read_text(encoding="utf-8"))

    def test_single_block_is_dataset(self):
        blocks = BLOCK.findall(self.html)
        self.assertEqual(len(blocks), 1)
        d = json.loads(blocks[0])
        self.assertEqual(d["@type"], "Dataset")
        self.assertEqual(d["license"], "https://creativecommons.org/licenses/by/4.0/")
        self.assertEqual(d["dateModified"], self.stats["generated"])
        self.assertEqual(d["url"], self.stats["site"] + "/")
        self.assertEqual(d["publisher"]["name"], "formachines.ai")
        self.assertTrue(d["name"] and d["description"])
        dist = {x["contentUrl"]: x["encodingFormat"] for x in d["distribution"]}
        base = self.stats["site"]
        self.assertEqual(set(dist), {base + "/stats.json", base + "/today.json", base + "/feed.xml"})
        self.assertTrue(all(dist.values()))

    def test_no_other_script_tags(self):
        for p in PUB.rglob("*.html"):
            t = p.read_text(encoding="utf-8")
            self.assertEqual(len(re.findall(r"<script\b", t)), len(BLOCK.findall(t)), str(p))

    def test_no_third_party_urls_in_block(self):
        d = BLOCK.findall(self.html)[0]
        for u in re.findall(r"https?://([^/\"]+)", d):
            self.assertIn(u, {"agentsmd.formachines.ai", "formachines.ai", "creativecommons.org", "schema.org"})


if __name__ == "__main__":
    unittest.main()
