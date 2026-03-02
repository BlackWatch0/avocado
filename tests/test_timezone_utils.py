import os
import unittest
from unittest import mock

from avocado.timezone_utils import detect_host_timezone_name, resolve_effective_timezone


class TimezoneUtilsTests(unittest.TestCase):
    def test_resolve_effective_timezone_manual_invalid_fallback_utc(self) -> None:
        timezone_name = resolve_effective_timezone(
            configured_timezone="Invalid/Timezone",
            timezone_source="manual",
        )
        self.assertEqual(timezone_name, "UTC")

    def test_resolve_effective_timezone_prefers_host_env(self) -> None:
        with mock.patch.dict(os.environ, {"AVOCADO_HOST_TIMEZONE": "Asia/Shanghai"}, clear=False):
            timezone_name = resolve_effective_timezone(
                configured_timezone="UTC",
                timezone_source="host",
            )
        self.assertEqual(timezone_name, "Asia/Shanghai")

    def test_detect_host_timezone_returns_non_empty(self) -> None:
        timezone_name = detect_host_timezone_name()
        self.assertTrue(bool(str(timezone_name).strip()))


if __name__ == "__main__":
    unittest.main()
