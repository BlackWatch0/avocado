import unittest

from avocado.models import AIConfig, CalendarRulesConfig


class ModelsTests(unittest.TestCase):
    def test_ai_config_defaults_openai_base_url_and_prompt(self) -> None:
        cfg = AIConfig.from_dict({})
        self.assertEqual(cfg.base_url, "https://api.openai.com/v1")
        self.assertTrue(bool(cfg.system_prompt.strip()))

    def test_calendar_rules_per_calendar_defaults_normalized(self) -> None:
        cfg = CalendarRulesConfig.from_dict(
            {
                "user_calendar_id": "user-id",
                "user_calendar_name": "User Layer",
                "intake_calendar_id": "intake-id",
                "intake_calendar_name": "Inbox Layer",
                "per_calendar_defaults": {
                    "cal-1": {"mode": "IMMUTABLE", "locked": 1, "mandatory": 0},
                    "cal-2": {"mode": "invalid", "locked": False, "mandatory": True},
                    "": {"mode": "immutable"},
                }
            }
        )
        self.assertEqual(cfg.user_calendar_id, "user-id")
        self.assertEqual(cfg.user_calendar_name, "User Layer")
        self.assertEqual(cfg.intake_calendar_id, "intake-id")
        self.assertEqual(cfg.intake_calendar_name, "Inbox Layer")
        self.assertEqual(cfg.per_calendar_defaults["cal-1"]["mode"], "immutable")
        self.assertTrue(cfg.per_calendar_defaults["cal-1"]["locked"])
        self.assertFalse(cfg.per_calendar_defaults["cal-1"]["mandatory"])
        self.assertEqual(cfg.per_calendar_defaults["cal-2"]["mode"], "editable")
        self.assertNotIn("", cfg.per_calendar_defaults)


if __name__ == "__main__":
    unittest.main()

