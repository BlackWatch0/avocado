import unittest

from avocado.core.models import TaskDefaultsConfig
from avocado.task_block import (
    AI_TASK_END,
    AI_TASK_START,
    ai_task_payload_from_description,
    ensure_ai_task_block,
    parse_ai_task_block,
    set_ai_task_locked,
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
        self.assertNotIn(".lock", updated)

    def test_locked_field_supports_multiple_boolean_forms(self) -> None:
        truthy_values = ["1", "T", "t", "true", "TRUE"]
        falsy_values = ["0", "F", "f", "false", "FALSE", "Fause", "fause"]
        for raw in truthy_values:
            description = f"[AI Task]\nlocked: {raw}\nuser_intent: ''\n[/AI Task]"
            _, payload, _ = ensure_ai_task_block(description, self.defaults)
            self.assertTrue(payload["locked"], msg=f"expected truthy for {raw}")
        for raw in falsy_values:
            description = f"[AI Task]\nlocked: {raw}\nuser_intent: ''\n[/AI Task]"
            _, payload, _ = ensure_ai_task_block(description, self.defaults)
            self.assertFalse(payload["locked"], msg=f"expected falsy for {raw}")

    def test_ensure_block_extracts_dot_m_user_intent_and_removes_marker(self) -> None:
        description = "打游戏\n.m 推迟30分钟"
        updated, payload, changed = ensure_ai_task_block(description, self.defaults)
        self.assertTrue(changed)
        self.assertEqual(payload["user_intent"], "推迟30分钟")
        self.assertIn("user_intent: 推迟30分钟", updated)
        self.assertNotIn(".m 推迟30分钟", updated)

    def test_ensure_block_supports_uppercase_dot_m(self) -> None:
        description = "Review notes\n.M move to tomorrow 10am"
        updated, payload, changed = ensure_ai_task_block(description, self.defaults)
        self.assertTrue(changed)
        self.assertEqual(payload["user_intent"], "move to tomorrow 10am")
        self.assertNotIn(".M move to tomorrow 10am", updated)

    def test_ensure_block_removes_orphan_ai_task_marker_before_upsert(self) -> None:
        description = "内容正文\n\n[AI Task]"
        updated, payload, changed = ensure_ai_task_block(description, self.defaults)
        self.assertTrue(changed)
        self.assertEqual(payload["user_intent"], "")
        self.assertEqual(updated.count("[AI Task]"), 1)
        self.assertEqual(updated.count("[/AI Task]"), 1)

    def test_set_ai_task_locked_updates_locked_flag(self) -> None:
        description = "Task body\n\n[AI Task]\nlocked: false\nuser_intent: ''\n[/AI Task]"
        updated, payload, changed = set_ai_task_locked(description, self.defaults, True)
        self.assertTrue(changed)
        self.assertTrue(bool(payload.get("locked")))
        self.assertIn("locked: true", updated)

    def test_strip_ai_task_block_removes_orphan_markers(self) -> None:
        description = "Visible\n[AI Task]\nVisible 2\n[/AI Task]\n[AI Task]"
        stripped = strip_ai_task_block(description)
        self.assertEqual(stripped, "Visible")


if __name__ == "__main__":
    unittest.main()
