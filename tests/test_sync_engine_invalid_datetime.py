import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from avocado.config_manager import ConfigManager
from avocado.models import CalendarInfo, EventRecord
from avocado.state_store import StateStore
from avocado.sync_engine import SyncEngine


class _FakeCalDAVService:
    def __init__(self, _config) -> None:
        self.staging_id = "cal-stage"
        self.user_id = "cal-user"
        self.intake_id = "cal-intake"
        self._calendars = [
            CalendarInfo(calendar_id=self.staging_id, name="Avocado AI Staging", url=self.staging_id),
            CalendarInfo(calendar_id=self.user_id, name="Avocado User Calendar", url=self.user_id),
            CalendarInfo(calendar_id=self.intake_id, name="Avocado New Events", url=self.intake_id),
        ]
        self._events: dict[str, dict[str, EventRecord]] = {
            self.staging_id: {},
            self.user_id: {
                "uid-1": EventRecord(
                    calendar_id=self.user_id,
                    uid="uid-1",
                    summary="Task 1",
                    description=(
                        "[AI Task]\n"
                        "locked: false\n"
                        "mandatory: false\n"
                        "user_intent: move this\n"
                        "[/AI Task]"
                    ),
                    start=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
                    end=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
                    etag="etag-1",
                ),
                "uid-2": EventRecord(
                    calendar_id=self.user_id,
                    uid="uid-2",
                    summary="Task 2",
                    description=(
                        "[AI Task]\n"
                        "locked: false\n"
                        "mandatory: false\n"
                        "user_intent: rename this\n"
                        "[/AI Task]"
                    ),
                    start=datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc),
                    end=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
                    etag="etag-2",
                ),
            },
            self.intake_id: {},
        }

    def list_calendars(self) -> list[CalendarInfo]:
        return list(self._calendars)

    def ensure_staging_calendar(self, calendar_id: str, staging_name: str) -> CalendarInfo:
        if calendar_id:
            for item in self._calendars:
                if item.calendar_id == calendar_id:
                    return item
        for item in self._calendars:
            if item.name == staging_name:
                return item
        raise RuntimeError("unknown staging calendar")

    def suggest_immutable_calendar_ids(self, calendars, keywords):
        return set()

    def fetch_events(self, calendar_id: str, _start, _end) -> list[EventRecord]:
        return [event.clone() for event in self._events.get(calendar_id, {}).values()]

    def upsert_event(self, calendar_id: str, event: EventRecord) -> EventRecord:
        updated = event.clone()
        updated.calendar_id = calendar_id
        updated.href = updated.href or f"{calendar_id}/{updated.uid}.ics"
        updated.etag = f"{updated.uid}-etag-updated"
        self._events.setdefault(calendar_id, {})[updated.uid] = updated
        return updated.clone()

    def delete_event(self, calendar_id: str, uid: str, href: str = "") -> bool:
        existed = uid in self._events.get(calendar_id, {})
        self._events.get(calendar_id, {}).pop(uid, None)
        return existed

    def get_event_by_uid(self, calendar_id: str, uid: str) -> EventRecord | None:
        event = self._events.get(calendar_id, {}).get(uid)
        return event.clone() if event else None


class _FakeAIClient:
    def __init__(self, _config) -> None:
        pass

    def is_configured(self) -> bool:
        return True

    def generate_changes(self, *, messages):
        return {
            "changes": [
                {
                    "calendar_id": "cal-user",
                    "uid": "uid-1",
                    "start": "not-a-datetime",
                    "reason": "bad output",
                },
                {
                    "calendar_id": "cal-user",
                    "uid": "uid-2",
                    "summary": "Task 2 Updated",
                    "reason": "good output",
                },
            ]
        }


class SyncEngineInvalidDatetimeTests(unittest.TestCase):
    def test_invalid_datetime_does_not_fail_whole_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_path = root / "config.yaml"
            db_path = root / "state.db"
            manager = ConfigManager(config_path)
            manager.update(
                {
                    "caldav": {
                        "base_url": "https://example.test/caldav",
                        "username": "user",
                        "password": "pass",
                    },
                    "ai": {
                        "base_url": "https://example.test/v1",
                        "api_key": "token",
                        "model": "gpt-test",
                    },
                    "calendar_rules": {
                        "staging_calendar_id": "cal-stage",
                        "user_calendar_id": "cal-user",
                        "intake_calendar_id": "cal-intake",
                    },
                }
            )
            store = StateStore(str(db_path))
            engine = SyncEngine(manager, store)

            with (
                mock.patch("avocado.sync_engine.CalDAVService", _FakeCalDAVService),
                mock.patch("avocado.sync_engine.OpenAICompatibleClient", _FakeAIClient),
            ):
                result = engine.run_once(trigger="manual")

            self.assertEqual(result.status, "success")
            self.assertEqual(result.changes_applied, 1)
            self.assertEqual(result.conflicts, 1)

            audit_events = store.recent_audit_events(limit=200)
            self.assertTrue(
                any(
                    item["action"] == "ai_change_invalid_datetime"
                    and item["details"].get("uid") == "uid-1"
                    for item in audit_events
                )
            )
            self.assertTrue(
                any(
                    item["action"] == "apply_ai_change"
                    and item["uid"] == "uid-2"
                    and item["details"].get("title") == "Task 2 Updated"
                    for item in audit_events
                )
            )


if __name__ == "__main__":
    unittest.main()
