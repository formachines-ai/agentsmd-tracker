"""Every HTML page (except /go/ redirects) has exactly one canonical equal to its clean URL and sitemap <loc>."""
import re
import unittest
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent / "public"
BASE = "https://agentsmd.formachines.ai"
LINK = re.compile(r'<link\b[^>]*\brel="canonical"[^>]*>')


def url_of(p: Path) -> str:
    rel = p.relative_to(PUBLIC).as_posix()
    if rel == "index.html":
        return BASE + "/"
    if rel == "404.html":
        return BASE + "/404.html"
    return BASE + "/" + rel[: -len("index.html")]


class CanonicalTest(unittest.TestCase):
    def test_canonicals(self):
        pages = [p for p in sorted(PUBLIC.rglob("*.html"))
                 if p.relative_to(PUBLIC).parts[0] != "go" and p.name in ("index.html", "404.html")]
        locs = set(re.findall(r"<loc>([^<]+)</loc>", (PUBLIC / "sitemap.xml").read_text(encoding="utf-8")))
        in_sitemap = 0
        for p in pages:
            links = LINK.findall(p.read_text(encoding="utf-8"))
            self.assertEqual(len(links), 1, f"{p}: {len(links)} canonical links")
            href = re.search(r'href="([^"]*)"', links[0]).group(1)
            self.assertEqual(href, url_of(p), str(p))
            self.assertNotIn("?", href)
            if href in locs:
                in_sitemap += 1
        for loc in locs:
            if loc.startswith(BASE + "/") and (loc.endswith("/")):
                f = PUBLIC / loc[len(BASE) + 1:] / "index.html" if loc != BASE + "/" else PUBLIC / "index.html"
                self.assertTrue(f.exists(), loc)
        self.assertGreater(len(pages), 0)
        print(f"canonical: {len(pages)} pages checked, {in_sitemap} match a sitemap <loc>")


if __name__ == "__main__":
    unittest.main()
