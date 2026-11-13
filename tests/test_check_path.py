"""Offline test of build.check_path for the .cursor/rules tree URL (stubbed HEAD, no network).
Run: python3 -B -m unittest tests.test_check_path -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build  # noqa: E402

REPO = {"full_name": "old/name", "default_branch": "main"}
SPEC = {"path": ".cursor/rules", "kind": "dir"}
START = "https://github.com/old/name/tree/main/.cursor/rules"
SAME = "https://github.com/new/name/tree/main/.cursor/rules"
ELSEWHERE = "https://github.com/old/name/tree/master/.cursor/rules"


def run(answers):
    def fake(url, token=None):
        a = answers[url]
        if isinstance(a, Exception):
            raise a
        return a
    with mock.patch.object(build, "head", side_effect=fake):
        return build.check_path(REPO, SPEC)


class CheckPath(unittest.TestCase):
    def test_200(self):
        self.assertEqual(run({START: (200, {})}), {"present": True, "size": None})

    def test_301_same_path_ends_200(self):
        r = run({START: (301, {"Location": SAME}), SAME: (200, {})})
        self.assertTrue(r["present"])

    def test_301_same_path_ends_404(self):
        self.assertFalse(run({START: (301, {"Location": SAME}), SAME: (404, {})})["present"])

    def test_301_elsewhere(self):
        r = run({START: (301, {"Location": ELSEWHERE})})
        self.assertEqual(r, {"present": False, "size": None})

    def test_404(self):
        self.assertFalse(run({START: (404, {})})["present"])

    def test_network_error(self):
        self.assertIsNone(run({START: (0, {})}))


if __name__ == "__main__":
    unittest.main()
