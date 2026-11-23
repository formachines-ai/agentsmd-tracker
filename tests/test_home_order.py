"""Offline (T-0246): by-language table and the static 'Find a repository' line come before the first per-file card; every /lang/ link resolves."""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent


class HomeOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="home-order-"))
        shutil.copy(REPO / "build.py", cls.tmp / "build.py")
        shutil.copytree(REPO / "static", cls.tmp / "static")
        shutil.copytree(REPO / "data", cls.tmp / "data")
        (cls.tmp / "public").mkdir()
        subprocess.run(["chmod", "-R", "u+w", str(cls.tmp)], check=True)
        subprocess.run([sys.executable, "-B", "build.py", "--no-scan"], cwd=cls.tmp, check=True, capture_output=True)
        cls.pub = cls.tmp / "public"
        cls.html = (cls.pub / "index.html").read_text()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_order(self):
        h = self.html
        find = h.index("Find a repository")
        table = h.index("<h2>By language</h2>")
        card = h.index('<section class="card">')
        self.assertLess(table, card)
        self.assertLess(find, h.index("<table", table))
        self.assertLess(find, card)
        self.assertIn("/repo/&lt;owner&gt;/&lt;name&gt;/", h[find:table + 600])

    def test_lang_links_resolve(self):
        h = self.html
        line = h[h.index('id="find-repo"'):]
        line = line[:line.index("</p>")]
        links = re.findall(r'href="(/lang/[^"]+/)"', line)
        self.assertTrue(links)
        table = h[h.index("<h2>By language</h2>"):h.index("</table>")]
        self.assertEqual(set(links), set(re.findall(r'href="(/lang/[^"]+/)"', table)))
        for l in links:
            self.assertTrue((self.pub / l.strip("/") / "index.html").is_file(), l)
        self.assertNotIn("<form", h)


if __name__ == "__main__":
    unittest.main()
