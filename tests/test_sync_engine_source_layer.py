import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from avocado.config_manager import ConfigManager
from avocado.core.models import CalendarInfo, EventRecord
from avocado.persistence.state_store import StateStore
from avocado.sync import SyncEngine


class _FakeCalDAVService:
    source_calendar_id = "source-cal"
    stack_calendar_id = "stack-cal"
    user_calendar_id = "user-cal"
    new_calendar_id = "new-cal"

    def __init__(self, _config: object) -> None:
        start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
        end = start + timedelta(hours=1)
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
            self.stack_calendar_id: {},
            self.user_calendar_id: {},
            self.new_calendar_id: {},
        }
        self.upsert_calls: list[tuple[str, EventRecord]] = []

    def list_calendars(self) -> list[CalendarInfo]:
        return [
            CalendarInfo(calendar_id=self.source_calendar_id, name="Personal", url=self.source_calendar_id),
            CalendarInfo(calendar_id=self.stack_calendar_id, name="Avocado Stack Calendar", url=self.stack_calendar_id),
            CalendarInfo(calendar_id=self.user_calendar_id, name="Avocado User Calendar", url=self.user_calendar_id),
            CalendarInfo(calendar_id=self.new_calendar_id, name="Avocado New Calendar", url=self.new_calendar_id),
        ]

    def ensure_managed_calendar(self, calendar_id: str, calendar_name: str) -> CalendarInfo:
        cid = calendar_id
        if not cid:
            mapping = {
                "Avocado Stack Calendar": self.stack_calendar_id,
                "Avocado User Calendar": self.user_calendar_id,
                "Avocado New Calendar": self.new_calendar_id,
            }
            cid = mapping[calendar_name]
        return CalendarInfo(calendar_id=cid, name=calendar_name, url=cid)

    def fetch_changes_by_token(self, calendar_id: str, _token: str) -> dict:
        return {
            "supported": True,
            "add_update": [],
            "delete": [],
            "next_token": f"next-{calendar_id}",
        }

    def list_window_index(self, calendar_id: str, _start: datetime, _end: datetime) -> list[dict]:
        return [
            {
                "uid": event.uid,
                "href": event.href or f"{calendar_id}/{event.uid}.ics",
                "etag": event.etag,
            }
            for event in self.events_by_calendar.get(calendar_id, {}).values()
        ]

    def fetch_events(self, calendar_id: str, _start: datetime, _end: datetime) -> list[EventRecord]:
        return [item.clone() for item in self.events_by_calendar.get(calendar_id, {}).values()]

    def upsert_event(self, calendar_id: str, event: EventRecord, expected_etag: str = "") -> EventRecord:
        current = self.events_by_calendar.setdefault(calendar_id, {}).get(event.uid)
        if expected_etag and current is not None and current.etag and current.etag != expected_etag:
            raise RuntimeError("etag_conflict")
        saved = event.clone()
        saved.calendar_id = calendar_id
        saved.etag = f"etag-{calendar_id}-{saved.uid}"
        saved.href = saved.href or f"{calendar_id}/{saved.uid}.ics"
        self.events_by_calendar.setdefault(calendar_id, {})[saved.uid] = saved
        self.upsert_calls.append((calendar_id, saved.clone()))
        return saved

    def delete_event(self, calendar_id: str, uid: str, href: str = "") -> bool:
        _ = href
        return bool(self.events_by_calendar.get(calendar_id, {}).pop(uid, None))

    def delete_event_with_etag(self, calendar_id: str, uid: str, expected_etag: str = "", href: str = "") -> bool:
        _ = expected_etag
        return self.delete_event(calendar_id, uid, href=href)

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
                "ai": {"enabled": False},
                "calendar_rules": {
                    "stack_calendar_id": _FakeCalDAVService.stack_calendar_id,
                    "stack_calendar_name": "Avocado Stack Calendar",
                    "user_calendar_id": _FakeCalDAVService.user_calendar_id,
                    "user_calendar_name": "Avocado User Calendar",
                    "new_calendar_id": _FakeCalDAVService.new_calendar_id,
                    "new_calendar_name": "Avocado New Calendar",
                },
            }
        )
        self.engine = SyncEngine(config_manager=config_manager, state_store=StateStore(str(self.state_path)))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sync_keeps_source_calendar_unchanged_and_writes_x_fields(self) -> None:
        fake_service = _FakeCalDAVService(object())
        source_uid = "source-uid"

        with mock.patch("avocado.sync.pipeline.CalDAVService", return_value=fake_service):
            result = self.engine.run_once(trigger="manual")

        self.assertEqual(result.status, "success")

        source_upserts = [event for cid, event in fake_service.upsert_calls if cid == _FakeCalDAVService.source_calendar_id]
        self.assertEqual(source_upserts, [])

        source_event_after = fake_service.events_by_calendar[_FakeCalDAVService.source_calendar_id][source_uid]
        self.assertEqual(source_event_after.description, "Original source description")

        stack_events = list(fake_service.events_by_calendar[_FakeCalDAVService.stack_calendar_id].values())
        user_events = list(fake_service.events_by_calendar[_FakeCalDAVService.user_calendar_id].values())
        self.assertGreaterEqual(len(stack_events), 1)
        self.assertGreaterEqual(len(user_events), 1)
        self.assertTrue(stack_events[0].x_sync_id)
        self.assertTrue(user_events[0].x_sync_id)
        self.assertEqual(stack_events[0].x_source, user_events[0].x_source)


if __name__ == "__main__":
    unittest.main()



