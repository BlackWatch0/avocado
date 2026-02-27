import unittest
from datetime import datetime, timezone

from avocado.models import EventRecord
from avocado.reconciler import apply_change


class ReconcilerTests(unittest.TestCase):
    def test_apply_change_success(self) -> None:
        event = EventRecord(
            calendar_id="cal-1",
            uid="uid-1",
            summary="Old",
            description="Desc",
            location="Office",
            start=datetime(2026, 2, 27, 9, 0, tzinfo=timezone.utc),
            end=datetime(2026, 2, 27, 10, 0, tzinfo=timezone.utc),
            etag="etag-a",
        )
        outcome = apply_change(
            current_event=event,
            change={
                "summary": "New",
                "start": "2026-02-27T11:00:00Z",
                "end": "2026-02-27T12:00:00Z",
            },
            baseline_etag="etag-a",
        )
        self.assertTrue(outcome.applied)
        self.assertFalse(outcome.conflicted)
        self.assertEqual(outcome.event.summary, "New")
        self.assertEqual(outcome.event.start.hour, 11)

    def test_conflict_when_user_modified(self) -> None:
        event = EventRecord(calendar_id="cal-1", uid="uid-1", etag="etag-new")
        outcome = apply_change(
            current_event=event,
            change={"summary": "New"},
            baseline_etag="etag-old",
        )
        self.assertFalse(outcome.applied)
        self.assertTrue(outcome.conflicted)
        self.assertEqual(outcome.reason, "user_modified_after_planning")

    def test_conflict_when_datetime_invalid(self) -> None:
        event = EventRecord(calendar_id="cal-1", uid="uid-1", etag="etag-a")
        outcome = apply_change(
            current_event=event,
            change={"start": "not-a-datetime", "summary": "New"},
            baseline_etag="etag-a",
        )
        self.assertFalse(outcome.applied)
        self.assertTrue(outcome.conflicted)
        self.assertEqual(outcome.reason, "invalid_datetime")
        self.assertEqual(outcome.event.summary, "")

    def test_conflict_when_locked(self) -> None:
        event = EventRecord(calendar_id="cal-1", uid="uid-1", locked=True, etag="etag-a")
        outcome = apply_change(
            current_event=event,
            change={"summary": "New"},
            baseline_etag="etag-a",
        )
        self.assertFalse(outcome.applied)
        self.assertTrue(outcome.conflicted)
        self.assertEqual(outcome.reason, "event_locked_or_mandatory")


if __name__ == "__main__":
    unittest.main()

