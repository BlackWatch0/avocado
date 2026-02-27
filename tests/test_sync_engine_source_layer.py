import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from avocado.config_manager import ConfigManager
from avocado.models import CalendarInfo, EventRecord
from avocado.state_store import StateStore
from avocado.sync_engine import SyncEngine, _staging_uid


class _FakeCalDAVService:
    source_calendar_id = "source-cal"
    staging_calendar_id = "stage-cal"
    user_calendar_id = "user-cal"
    intake_calendar_id = "intake-cal"

    def __init__(self, _config: object) -> None:
        start = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
        self.events_by_calendar = {
            self.source_calendar_id: {
                "source-uid": EventRecord(
                    calendar_id=self.source_calendar_id,
                    uid="source-uid",
                    summary="Source Event",
                    description="Original source description",
                    start=start,
                    end=end,
                    etag="src-etag",
                )
            },
            self.staging_calendar_id: {},
            self.user_calendar_id: {},
            self.intake_calendar_id: {},
        }
        self.upsert_calls: list[tuple[str, EventRecord]] = []

    def list_calendars(self) -> list[CalendarInfo]:
        return [
            CalendarInfo(calendar_id=self.source_calendar_id, name="Personal", url=self.source_calendar_id),
            CalendarInfo(calendar_id=self.staging_calendar_id, name="Avocado AI Staging", url=self.staging_calendar_id),
            CalendarInfo(calendar_id=self.user_calendar_id, name="Avocado User Calendar", url=self.user_calendar_id),
            CalendarInfo(calendar_id=self.intake_calendar_id, name="Avocado New Events", url=self.intake_calendar_id),
        ]

    def ensure_staging_calendar(self, calendar_id: str, calendar_name: str) -> CalendarInfo:
        cid = calendar_id
        if not cid:
            mapping = {
                "Avocado AI Staging": self.staging_calendar_id,
                "Avocado User Calendar": self.user_calendar_id,
                "Avocado New Events": self.intake_calendar_id,
            }
            cid = mapping[calendar_name]
        return CalendarInfo(calendar_id=cid, name=calendar_name, url=cid)

    def suggest_immutable_calendar_ids(self, calendars: list[CalendarInfo], keywords: list[str]) -> set[str]:
        return set()

    def fetch_events(self, calendar_id: str, _start: datetime, _end: datetime) -> list[EventRecord]:
        return [item.clone() for item in self.events_by_calendar.get(calendar_id, {}).values()]

    def upsert_event(self, calendar_id: str, event: EventRecord) -> EventRecord:
        saved = event.clone()
        saved.calendar_id = calendar_id
        saved.etag = f"etag-{calendar_id}-{saved.uid}"
        self.events_by_calendar.setdefault(calendar_id, {})[saved.uid] = saved
        self.upsert_calls.append((calendar_id, saved.clone()))
        return saved

    def delete_event(self, calendar_id: str, uid: str, href: str = "") -> bool:
        calendar_events = self.events_by_calendar.get(calendar_id, {})
        if uid in calendar_events:
            del calendar_events[uid]
            return True
        return False

    def get_event_by_uid(self, calendar_id: str, uid: str) -> EventRecord | None:
        event = self.events_by_calendar.get(calendar_id, {}).get(uid)
        return event.clone() if event is not None else None


class SyncEngineSourceLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config.yaml"
        self.state_path = Path(self.temp_dir.name) / "state.db"
        config_manager = ConfigManager(self.config_path)
        config_manager.update(
            {
                "caldav": {
                    "base_url": "https://dav.example.com",
                    "username": "tester",
                    "password": "pw",
                },
                "ai": {"api_key": ""},
                "calendar_rules": {
                    "staging_calendar_id": _FakeCalDAVService.staging_calendar_id,
                    "staging_calendar_name": "Avocado AI Staging",
                    "user_calendar_id": _FakeCalDAVService.user_calendar_id,
                    "user_calendar_name": "Avocado User Calendar",
                    "intake_calendar_id": _FakeCalDAVService.intake_calendar_id,
                    "intake_calendar_name": "Avocado New Events",
                    "immutable_calendar_ids": [],
                    "per_calendar_defaults": {
                        _FakeCalDAVService.source_calendar_id: {
                            "mode": "editable",
                            "locked": False,
                            "mandatory": False,
                        }
                    },
                },
            }
        )
        self.engine = SyncEngine(config_manager=config_manager, state_store=StateStore(str(self.state_path)))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sync_keeps_source_description_and_adds_ai_block_only_to_user_layer(self) -> None:
        fake_service = _FakeCalDAVService(object())
        source_uid = "source-uid"
        user_uid = _staging_uid(_FakeCalDAVService.source_calendar_id, source_uid)

        with mock.patch("avocado.sync_engine.CalDAVService", return_value=fake_service):
            result = self.engine.run_once(trigger="manual")

        self.assertEqual(result.status, "success")

        source_upserts = [event for cid, event in fake_service.upsert_calls if cid == _FakeCalDAVService.source_calendar_id]
        self.assertEqual(source_upserts, [])

        source_event_after = fake_service.events_by_calendar[_FakeCalDAVService.source_calendar_id][source_uid]
        self.assertEqual(source_event_after.description, "Original source description")
        self.assertNotIn("[AI Task]", source_event_after.description)

        user_event = fake_service.events_by_calendar[_FakeCalDAVService.user_calendar_id][user_uid]
        self.assertIn("[AI Task]", user_event.description)
        self.assertIn("locked:", user_event.description)
        self.assertNotIn("mandatory:", user_event.description)


if __name__ == "__main__":
    unittest.main()
