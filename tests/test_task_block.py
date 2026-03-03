import unittest

from avocado.core.models import TaskDefaultsConfig
from avocado.task_block import (
    AI_TASK_END,
    AI_TASK_START,
    ai_task_payload_from_description,
    ensure_ai_task_block,
    parse_ai_task_block,
    strip_ai_task_block,
)


class TaskBlockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.defaults = TaskDefaultsConfig(
            locked=False,
            editable_fields=["start", "end", "summary", "location", "description"],
        )

    def test_ensure_block_injects_when_missing(self) -> None:
        description = "Team planning session"
        updated, payload, changed = ensure_ai_task_block(description, self.defaults)
        self.assertTrue(changed)
        self.assertIn(AI_TASK_START, updated)
        self.assertIn(AI_TASK_END, updated)
        self.assertFalse(payload["locked"])
        self.assertNotIn("mandatory", payload)

    def test_parse_and_strip(self) -> None:
        description = "Hello\n\n[AI Task]\nlocked: true\n[/AI Task]"
        parsed = parse_ai_task_block(description)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertTrue(parsed["locked"])
        self.assertEqual(strip_ai_task_block(description), "Hello")


    def test_parse_invalid_yaml_returns_none(self) -> None:
        description = """Hello\n\n[AI Task]\nuser_intent: "move around 3pm\nlocked: false\n[/AI Task]"""
        self.assertIsNone(parse_ai_task_block(description))

    def test_ensure_block_normalizes_null_user_intent(self) -> None:
        description = "Task\n\n[AI Task]\nlocked: false\nuser_intent:\n[/AI Task]"
        updated, payload, changed = ensure_ai_task_block(description, self.defaults)
        self.assertTrue(changed)
        self.assertEqual(payload["user_intent"], "")
        self.assertIn("user_intent: ''", updated)

    def test_ai_task_payload_from_description(self) -> None:
        description = (
            "Visible text\n\n"
            "[AI Task]\n"
            "version: 2\n"
            "locked: false\n"
            "user_intent: postpone 30 minutes\n"
            "[/AI Task]"
        )
        visible, ai_task, x_meta = ai_task_payload_from_description(description, self.defaults)
        self.assertEqual(visible, "Visible text")
        self.assertEqual(ai_task.get("user_intent"), "postpone 30 minutes")
        self.assertEqual(set(ai_task.keys()), {"locked", "user_intent"})
        self.assertEqual(x_meta, {})

    def test_ensure_block_locks_when_description_contains_dot_lock(self) -> None:
        description = "Prepare release notes .lock"
        updated, payload, changed = ensure_ai_task_block(description, self.defaults)
        self.assertTrue(changed)
        self.assertTrue(payload["locked"])
        self.assertIn("locked: true", updated)


if __name__ == "__main__":
    unittest.main()
