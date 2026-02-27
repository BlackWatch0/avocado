from datetime import datetime, timedelta, timezone
from unittest import TestCase, mock

from avocado.models import AppConfig, CalendarInfo, EventRecord
from avocado.sync_engine import SyncEngine


class SyncEngineRunOnceTests(TestCase):
    def test_immutable_events_do_not_trigger_upsert_writeback(self) -> None:
        config = AppConfig.from_dict(
            {
                "caldav": {
                    "base_url": "https://caldav.example.com",
                    "username": "tester",
                    "password": "secret",
                },
                "calendar_rules": {
                    "staging_calendar_id": "stage-cal",
                    "staging_calendar_name": "Avocado AI Staging",
                    "user_calendar_id": "user-cal",
                    "user_calendar_name": "Avocado User Calendar",
                    "intake_calendar_id": "intake-cal",
                    "intake_calendar_name": "Avocado New Events",
                    "immutable_calendar_ids": ["immutable-cal"],
                    "per_calendar_defaults": {
                        "immutable-cal": {"mode": "immutable", "locked": True, "mandatory": True}
                    },
                },
            }
        )

        config_manager = mock.Mock()
        config_manager.load.return_value = config

        state_store = mock.Mock()
        state_store.record_sync_run.return_value = 1
        state_store.get_meta.return_value = None

        source_event = EventRecord(
            calendar_id="immutable-cal",
            uid="immutable-uid-1",
            summary="Immutable Event",
            description="Source event without AI metadata",
            start=datetime.now(timezone.utc),
            end=datetime.now(timezone.utc) + timedelta(hours=1),
            etag="etag-1",
        )

        calendars = [
            CalendarInfo(calendar_id="immutable-cal", name="Work", url="https://example/immutable"),
            CalendarInfo(calendar_id="stage-cal", name="Avocado AI Staging", url="https://example/stage"),
            CalendarInfo(calendar_id="user-cal", name="Avocado User Calendar", url="https://example/user"),
            CalendarInfo(calendar_id="intake-cal", name="Avocado New Events", url="https://example/intake"),
        ]

        caldav_service = mock.Mock()
        caldav_service.list_calendars.return_value = calendars
        caldav_service.suggest_immutable_calendar_ids.return_value = set()

        def ensure_staging_calendar(calendar_id: str, calendar_name: str) -> CalendarInfo:
            return CalendarInfo(calendar_id=calendar_id, name=calendar_name, url=f"https://example/{calendar_id}")

        caldav_service.ensure_staging_calendar.side_effect = ensure_staging_calendar

        def fetch_events(calendar_id: str, _window_start: datetime, _window_end: datetime) -> list[EventRecord]:
            if calendar_id == "immutable-cal":
                return [source_event]
            return []

        caldav_service.fetch_events.side_effect = fetch_events

        with mock.patch("avocado.sync_engine.CalDAVService", return_value=caldav_service):
            engine = SyncEngine(config_manager, state_store)
            result = engine.run_once(trigger="manual")

        self.assertEqual(result.status, "success")
        self.assertEqual(caldav_service.upsert_event.call_count, 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
