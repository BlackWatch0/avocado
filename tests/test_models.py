import unittest

from avocado.core.models import AIConfig, CalendarRulesConfig


class ModelsTests(unittest.TestCase):
    def test_ai_config_defaults_openai_base_url_and_prompt(self) -> None:
        cfg = AIConfig.from_dict({})
        self.assertEqual(cfg.base_url, "https://api.openai.com/v1")
        self.assertTrue(bool(cfg.system_prompt.strip()))
        self.assertEqual(cfg.high_load_model, "")
        self.assertEqual(cfg.high_load_event_threshold, 0)
        self.assertFalse(cfg.high_load_auto_enabled)
        self.assertEqual(cfg.high_load_auto_score_threshold, 0.65)
        self.assertEqual(cfg.high_load_auto_event_baseline, 12)
        self.assertFalse(cfg.high_load_use_flex)
        self.assertTrue(cfg.high_load_flex_fallback_to_auto)

    def test_ai_config_high_load_fields(self) -> None:
        cfg = AIConfig.from_dict(
            {
                "model": "gpt-4o-mini",
                "high_load_model": "gpt-5",
                "high_load_event_threshold": 20,
            }
        )
        self.assertEqual(cfg.model, "gpt-4o-mini")
        self.assertEqual(cfg.high_load_model, "gpt-5")
        self.assertEqual(cfg.high_load_event_threshold, 20)
        self.assertFalse(cfg.high_load_use_flex)
        self.assertTrue(cfg.high_load_flex_fallback_to_auto)

    def test_ai_config_high_load_flex_flag(self) -> None:
        cfg = AIConfig.from_dict(
            {
                "high_load_model": "gpt-5",
                "high_load_event_threshold": 12,
                "high_load_auto_enabled": True,
                "high_load_auto_score_threshold": 0.72,
                "high_load_auto_event_baseline": 9,
                "high_load_use_flex": True,
            }
        )
        self.assertTrue(cfg.high_load_auto_enabled)
        self.assertEqual(cfg.high_load_auto_score_threshold, 0.72)
        self.assertEqual(cfg.high_load_auto_event_baseline, 9)
        self.assertTrue(cfg.high_load_use_flex)

    def test_ai_config_high_load_flex_fallback_flag(self) -> None:
        cfg = AIConfig.from_dict(
            {
                "high_load_use_flex": True,
                "high_load_flex_fallback_to_auto": False,
            }
        )
        self.assertTrue(cfg.high_load_use_flex)
        self.assertFalse(cfg.high_load_flex_fallback_to_auto)

    def test_calendar_rules_fields_use_stack_user_new(self) -> None:
        cfg = CalendarRulesConfig.from_dict(
            {
                "user_calendar_id": "user-id",
                "user_calendar_name": "User Layer",
                "new_calendar_id": "new-id",
                "new_calendar_name": "Inbox Layer",
                "stack_calendar_id": "stack-id",
                "stack_calendar_name": "Stack Layer",
            }
        )
        self.assertEqual(cfg.stack_calendar_id, "stack-id")
        self.assertEqual(cfg.stack_calendar_name, "Stack Layer")
        self.assertEqual(cfg.user_calendar_id, "user-id")
        self.assertEqual(cfg.user_calendar_name, "User Layer")
        self.assertEqual(cfg.new_calendar_id, "new-id")
        self.assertEqual(cfg.new_calendar_name, "Inbox Layer")


if __name__ == "__main__":
    unittest.main()
