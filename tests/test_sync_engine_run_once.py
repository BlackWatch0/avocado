import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase, mock

from avocado.config_manager import ConfigManager
from avocado.core.models import CalendarInfo, EventRecord
from avocado.persistence.state_store import StateStore
from avocado.sync import SyncEngine


class _FakeCalDAVService:
    source_calendar_id = "source-cal"
    stack_calendar_id = "stack-cal"
    user_calendar_id = "user-cal"
    new_calendar_id = "new-cal"

    def __init__(self, _config) -> None:
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        self.events_by_calendar = {
            self.source_calendar_id: {
                "source-uid": EventRecord(
                    calendar_id=self.source_calendar_id,
                    uid="source-uid",
                    summary="Source Event",
                    description="Original source description",
                    start=now + timedelta(hours=2),
                    end=now + timedelta(hours=3),
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


class SyncEngineRunOnceTests(TestCase):
    def test_external_source_event_syncs_to_stack_and_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manager = ConfigManager(root / "config.yaml")
            manager.update(
                {
                    "caldav": {
                        "base_url": "https://caldav.example.com",
                        "username": "tester",
                        "password": "secret",
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
            state_store = StateStore(str(root / "state.db"))
            fake_service = _FakeCalDAVService(object())

            with mock.patch("avocado.sync.pipeline.CalDAVService", return_value=fake_service):
                engine = SyncEngine(manager, state_store)
                result = engine.run_once(trigger="manual")

            self.assertEqual(result.status, "success")
            self.assertGreaterEqual(result.changes_applied, 2)

            source_upserts = [call for call in fake_service.upsert_calls if call[0] == _FakeCalDAVService.source_calendar_id]
            self.assertEqual(source_upserts, [])

            stack_upserts = [call for call in fake_service.upsert_calls if call[0] == _FakeCalDAVService.stack_calendar_id]
            user_upserts = [call for call in fake_service.upsert_calls if call[0] == _FakeCalDAVService.user_calendar_id]
            self.assertGreaterEqual(len(stack_upserts), 1)
            self.assertGreaterEqual(len(user_upserts), 1)


if __name__ == "__main__":
    import unittest

    unittest.main()



