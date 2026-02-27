import unittest

from avocado.sync_engine import (
    _collapse_nested_managed_uid,
    _managed_uid_prefix_depth,
    _normalize_calendar_name,
)


class SyncEngineHelperTests(unittest.TestCase):
    def test_normalize_calendar_name(self) -> None:
        self.assertEqual(_normalize_calendar_name("  Avocado   User Calendar "), "avocado user calendar")
        self.assertEqual(_normalize_calendar_name(""), "")

    def test_managed_uid_prefix_depth(self) -> None:
        self.assertEqual(_managed_uid_prefix_depth(""), 0)
        self.assertEqual(_managed_uid_prefix_depth("plain-uid"), 0)
        self.assertEqual(_managed_uid_prefix_depth("76044593b8:plain-uid"), 1)
        self.assertEqual(_managed_uid_prefix_depth("e426ae0ed4:76044593b8:plain-uid"), 2)

    def test_collapse_nested_managed_uid(self) -> None:
        self.assertEqual(
            _collapse_nested_managed_uid("e426ae0ed4:76044593b8:plain-uid"),
            "76044593b8:plain-uid",
        )
        self.assertEqual(
            _collapse_nested_managed_uid("aaaaaaaaaa:bbbbbbbbbb:cccccccccc:uid"),
            "cccccccccc:uid",
        )
        self.assertEqual(_collapse_nested_managed_uid("76044593b8:plain-uid"), "76044593b8:plain-uid")


if __name__ == "__main__":
    unittest.main()
