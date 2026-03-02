import argparse
import unittest
from datetime import datetime, timezone
from unittest import mock

from avocado.core.models import AppConfig
from avocado.tools.smoke_test import _window_from_args, main


class SmokeTestTests(unittest.TestCase):
    def test_window_from_args_defaults(self) -> None:
        start, end = _window_from_args(3, "", "")
        self.assertIsNotNone(start.tzinfo)
        self.assertIsNotNone(end.tzinfo)
        self.assertGreater(end, start)

    def test_window_from_args_custom(self) -> None:
        start, end = _window_from_args(
            7,
            "2026-03-01T00:00:00+00:00",
            "2026-03-02T00:00:00+00:00",
        )
        self.assertEqual(start, datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc))

    def test_window_from_args_invalid_range(self) -> None:
        with self.assertRaises(ValueError):
            _window_from_args(
                7,
                "2026-03-02T00:00:00+00:00",
                "2026-03-01T00:00:00+00:00",
            )

    def test_main_skip_checks_success(self) -> None:
        args = argparse.Namespace(
            config="config.yaml",
            state="data/state.db",
            skip_caldav=True,
            skip_ai=True,
            run_sync=False,
            start="",
            end="",
        )
        cfg = AppConfig.from_dict({})
        with mock.patch("avocado.tools.smoke_test._parse_args", return_value=args), mock.patch(
            "avocado.tools.smoke_test.ConfigManager"
        ) as manager_cls:
            manager_cls.return_value.load.return_value = cfg
            rc = main()
        self.assertEqual(rc, 0)

    def test_main_ai_failure_returns_nonzero(self) -> None:
        args = argparse.Namespace(
            config="config.yaml",
            state="data/state.db",
            skip_caldav=True,
            skip_ai=False,
            run_sync=False,
            start="",
            end="",
        )
        cfg = AppConfig.from_dict(
            {
                "ai": {
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "k",
                    "model": "gpt-4o-mini",
                }
            }
        )
        with mock.patch("avocado.tools.smoke_test._parse_args", return_value=args), mock.patch(
            "avocado.tools.smoke_test.ConfigManager"
        ) as manager_cls, mock.patch("avocado.tools.smoke_test.OpenAICompatibleClient") as ai_cls:
            manager_cls.return_value.load.return_value = cfg
            ai_cls.return_value.test_connectivity.return_value = (False, "bad key")
            rc = main()
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()


