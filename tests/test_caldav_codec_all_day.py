from __future__ import annotations

from datetime import datetime, timezone
import unittest

from avocado.core.models import EventRecord
from avocado.integrations.caldav.codec import build_ical, parse_resource


class _FakeResource:
    def __init__(self, data: str) -> None:
        self.data = data
        self.url = "https://example.test/event.ics"
        self.etag = ""
        self.props: dict[str, str] = {}


class CaldavCodecAllDayTests(unittest.TestCase):
    def test_parse_resource_preserves_all_day_exclusive_end(self) -> None:
        raw_ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:all-day-1\r\n"
            "SUMMARY:All Day\r\n"
            "DTSTART;VALUE=DATE:20260304\r\n"
            "DTEND;VALUE=DATE:20260305\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        parsed = parse_resource("stack-cal", _FakeResource(raw_ical))
        self.assertTrue(parsed.all_day)
        self.assertEqual(parsed.start, datetime(2026, 3, 4, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(parsed.end, datetime(2026, 3, 5, 0, 0, tzinfo=timezone.utc))

    def test_build_ical_writes_all_day_as_value_date(self) -> None:
        event = EventRecord(
            calendar_id="stack-cal",
            uid="all-day-2",
            summary="All Day",
            start=datetime(2026, 3, 4, 0, 0, tzinfo=timezone.utc),
            end=datetime(2026, 3, 5, 0, 0, tzinfo=timezone.utc),
            all_day=True,
        )
        ical = build_ical(event)
        self.assertIn("DTSTART;VALUE=DATE:20260304", ical)
        self.assertIn("DTEND;VALUE=DATE:20260305", ical)
        self.assertNotIn("DTSTART:20260304T", ical)


if __name__ == "__main__":
    unittest.main()
