from __future__ import annotations

from datetime import datetime, timezone
import unittest

from avocado.core.models import EventRecord
from avocado.reconciler import apply_change


class ReconcilerAllDayTests(unittest.TestCase):
    def test_apply_change_normalizes_all_day_time_range(self) -> None:
        current = EventRecord(
            calendar_id="stack-cal",
            uid="all-day-1",
            summary="All Day Event",
            start=datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc),
            end=datetime(2026, 3, 9, 0, 0, tzinfo=timezone.utc),
            all_day=True,
        )
        outcome = apply_change(
            current_event=current,
            change={
                "start": "2026-03-08T00:00:00+00:00",
                "end": "2026-03-08T12:00:00+00:00",
            },
            baseline_etag="",
            editable_fields=["start", "end", "summary", "location", "description"],
        )
        self.assertFalse(outcome.applied)
        self.assertEqual(outcome.event.start, datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(outcome.event.end, datetime(2026, 3, 9, 0, 0, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
