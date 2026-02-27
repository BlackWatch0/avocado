import unittest

from avocado.models import CalendarRulesConfig


class ModelsTests(unittest.TestCase):
    def test_calendar_rules_per_calendar_defaults_normalized(self) -> None:
        cfg = CalendarRulesConfig.from_dict(
            {
                "per_calendar_defaults": {
                    "cal-1": {"mode": "IMMUTABLE", "locked": 1, "mandatory": 0},
                    "cal-2": {"mode": "invalid", "locked": False, "mandatory": True},
                    "": {"mode": "immutable"},
                }
            }
        )
        self.assertEqual(cfg.per_calendar_defaults["cal-1"]["mode"], "immutable")
        self.assertTrue(cfg.per_calendar_defaults["cal-1"]["locked"])
        self.assertFalse(cfg.per_calendar_defaults["cal-1"]["mandatory"])
        self.assertEqual(cfg.per_calendar_defaults["cal-2"]["mode"], "editable")
        self.assertNotIn("", cfg.per_calendar_defaults)


if __name__ == "__main__":
    unittest.main()

