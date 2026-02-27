import unittest
from datetime import datetime, timezone

from avocado.models import EventRecord
from avocado.sync_engine import (
    _collapse_nested_managed_uid,
    _event_has_user_intent,
    _extract_user_intent,
    _managed_uid_prefix_depth,
    _normalize_calendar_name,
    _purge_duplicate_calendar_events,
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
            description="[AI Task]\nuser_intent: \"move before meal around 3pm\nlocked: false\n[/AI Task]",
        )
        self.assertTrue(_event_has_user_intent(event_with_non_yaml_intent))


    def test_extract_user_intent_with_invalid_yaml_fallback(self) -> None:
        event_with_non_yaml_intent = EventRecord(
            calendar_id="cal",
            uid="uid-5",
            description="[AI Task]\nuser_intent: \"move before meal around 3pm\nlocked: false\n[/AI Task]",
        )
        self.assertEqual(_extract_user_intent(event_with_non_yaml_intent), '"move before meal around 3pm')

    def test_extract_user_intent(self) -> None:
        event_with_intent = EventRecord(
            calendar_id="cal",
            uid="uid-4",
            description="[AI Task]\nuser_intent: move earlier by 30 minutes\n[/AI Task]",
        )
        self.assertEqual(_extract_user_intent(event_with_intent), "move earlier by 30 minutes")


class _FakeCalDAVService:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str, str]] = []

    def fetch_events(self, _calendar_id: str, _start: datetime, _end: datetime) -> list[EventRecord]:
        return [EventRecord(calendar_id="dup-cal", uid="evt-1", href="/evt-1.ics")]

    def delete_event(self, calendar_id: str, uid: str, href: str) -> bool:
        self.deleted.append((calendar_id, uid, href))
        return True


class _FakeStateStore:
    def __init__(self) -> None:
        self.audit_events: list[dict[str, object]] = []

    def record_audit_event(self, **kwargs: object) -> None:
        self.audit_events.append(kwargs)


class SyncEngineDuplicateCalendarCleanupTests(unittest.TestCase):
    def test_unverified_duplicate_calendar_is_not_deleted(self) -> None:
        service = _FakeCalDAVService()
        state_store = _FakeStateStore()

        should_replan = _purge_duplicate_calendar_events(
            caldav_service=service,
            state_store=state_store,
            duplicate_calendars=[("dup-cal", "Avocado User Calendar")],
            calendar_role="user",
            known_managed_calendar_ids={"known-managed-cal"},
            trigger="manual",
            window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

        self.assertFalse(should_replan)
        self.assertEqual(service.deleted, [])
        self.assertEqual(len(state_store.audit_events), 1)
        self.assertEqual(state_store.audit_events[0]["action"], "warn_unverified_duplicate_user_calendar")

    def test_verified_duplicate_calendar_is_deleted(self) -> None:
        service = _FakeCalDAVService()
        state_store = _FakeStateStore()

        should_replan = _purge_duplicate_calendar_events(
            caldav_service=service,
            state_store=state_store,
            duplicate_calendars=[("dup-cal", "Avocado User Calendar")],
            calendar_role="user",
            known_managed_calendar_ids={"dup-cal"},
            trigger="manual",
            window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

        self.assertTrue(should_replan)
        self.assertEqual(service.deleted, [("dup-cal", "evt-1", "/evt-1.ics")])
        self.assertEqual(len(state_store.audit_events), 1)
        self.assertEqual(state_store.audit_events[0]["action"], "purge_duplicate_user_calendar_event")


if __name__ == "__main__":
    unittest.main()
