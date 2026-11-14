"""Offline: moved_to / moved_detected detection with mocked HEAD responses. No network, no writes."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build  # noqa: E402

REPO = {"full_name": "Old/Name", "owner": "Old", "name": "Name"}


def moved(status, hdrs=None):
    with mock.patch.object(build, "head", return_value=(status, hdrs or {})) as h:
        res = build.check_moved(REPO)
    h.assert_called_once_with("https://github.com/Old/Name")
    return res


class CheckMoved(unittest.TestCase):
    def test_301_other_name(self):
        self.assertEqual(moved(301, {"Location": "https://github.com/new/repo"}), ("new/repo", True))

    def test_302_relative_location(self):
        self.assertEqual(moved(302, {"location": "/new/repo"}), ("new/repo", True))

    def test_case_only(self):
        self.assertEqual(moved(301, {"Location": "https://github.com/old/NAME"}), (None, True))

    def test_200(self):
        self.assertEqual(moved(200), (None, True))

    def test_404(self):
        self.assertEqual(moved(404), (None, False))

    def test_timeout(self):
        self.assertEqual(moved(0), (None, False))


class MergeMoved(unittest.TestCase):
    def test_first_detection_date_kept(self):
        prev = {"moved_to": "new/repo", "moved_detected": "2026-11-10"}
        new = {"checked": "2026-11-14T04:00:00Z", "moved_to": "new/repo"}
        build.merge_moved(prev, new)
        self.assertEqual(new["moved_detected"], "2026-11-10")

    def test_new_detection_gets_today(self):
        new = {"checked": "2026-11-14T04:00:00Z", "moved_to": "new/repo"}
        build.merge_moved({"moved_to": None, "moved_detected": None}, new)
        self.assertEqual((new["moved_to"], new["moved_detected"]), ("new/repo", "2026-11-14"))

    def test_unknown_answer_keeps_previous(self):
        prev = {"moved_to": "new/repo", "moved_detected": "2026-11-10"}
        new = {"checked": "2026-11-14T04:00:00Z"}
        build.merge_moved(prev, new)
        self.assertEqual((new["moved_to"], new["moved_detected"]), ("new/repo", "2026-11-10"))

    def test_live_is_null(self):
        new = {"checked": "2026-11-14T04:00:00Z", "moved_to": None}
        build.merge_moved(None, new)
        self.assertEqual((new["moved_to"], new["moved_detected"]), (None, None))


if __name__ == "__main__":
    unittest.main()
