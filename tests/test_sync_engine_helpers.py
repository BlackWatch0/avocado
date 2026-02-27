import unittest

from avocado.models import EventRecord
from avocado.sync_engine import (
    _collapse_nested_managed_uid,
    _event_has_user_intent,
    _extract_user_intent,
    _extract_editable_fields,
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

    def test_event_has_user_intent(self) -> None:
        event_without_intent = EventRecord(
            calendar_id="cal",
            uid="uid-1",
            description="[AI Task]\nlocked: false\nmandatory: false\nuser_intent: \"\"\n[/AI Task]",
        )
        event_with_intent = EventRecord(
            calendar_id="cal",
            uid="uid-2",
            description="[AI Task]\nlocked: false\nmandatory: false\nuser_intent: \"move to around 3pm\"\n[/AI Task]",
        )
        self.assertFalse(_event_has_user_intent(event_without_intent))
        self.assertTrue(_event_has_user_intent(event_with_intent))

    def test_event_has_user_intent_with_invalid_yaml_fallback(self) -> None:
        event_with_non_yaml_intent = EventRecord(
            calendar_id="cal",
            uid="uid-3",
            description="[AI Task]\nuser_intent: move before meal around 3pm)\n[/AI Task]",
        )
        self.assertTrue(_event_has_user_intent(event_with_non_yaml_intent))


    def test_extract_editable_fields_from_ai_task_block(self) -> None:
        event = EventRecord(
            calendar_id="cal",
            uid="uid-5",
            description=(
                "[AI Task]\nlocked: false\nmandatory: false\n"
                "editable_fields:\n  - start\n  - end\n[/AI Task]"
            ),
        )
        self.assertEqual(_extract_editable_fields(event, ["summary"]), ["start", "end"])

    def test_extract_user_intent(self) -> None:
        event_with_intent = EventRecord(
            calendar_id="cal",
            uid="uid-4",
            description="[AI Task]\nuser_intent: move earlier by 30 minutes\n[/AI Task]",
        )
        self.assertEqual(_extract_user_intent(event_with_intent), "move earlier by 30 minutes")


if __name__ == "__main__":
    unittest.main()
