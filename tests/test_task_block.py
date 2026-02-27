import unittest

from avocado.models import TaskDefaultsConfig
from avocado.task_block import (
    AI_TASK_END,
    AI_TASK_START,
    ensure_ai_task_block,
    parse_ai_task_block,
    set_ai_task_category,
    strip_ai_task_block,
)


class TaskBlockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.defaults = TaskDefaultsConfig(
            locked=False,
            mandatory=False,
            editable_fields=["start", "end", "summary", "location", "description"],
        )

    def test_ensure_block_injects_when_missing(self) -> None:
        description = "Team planning session"
        updated, payload, changed = ensure_ai_task_block(description, self.defaults)
        self.assertTrue(changed)
        self.assertIn(AI_TASK_START, updated)
        self.assertIn(AI_TASK_END, updated)
        self.assertFalse(payload["locked"])
        self.assertFalse(payload["mandatory"])

    def test_parse_and_strip(self) -> None:
        description = "Hello\n\n[AI Task]\nlocked: true\nmandatory: false\n[/AI Task]"
        parsed = parse_ai_task_block(description)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertTrue(parsed["locked"])
        self.assertFalse(parsed["mandatory"])
        self.assertEqual(strip_ai_task_block(description), "Hello")


    def test_parse_invalid_yaml_returns_none(self) -> None:
        description = """Hello\n\n[AI Task]\nuser_intent: "move around 3pm\nlocked: false\n[/AI Task]"""
        self.assertIsNone(parse_ai_task_block(description))

    def test_set_category(self) -> None:
        description = "Task event"
        updated, payload, changed = set_ai_task_category(description, self.defaults, "study")
        self.assertTrue(changed)
        self.assertIn(AI_TASK_START, updated)
        self.assertEqual(payload["category"], "study")


if __name__ == "__main__":
    unittest.main()

