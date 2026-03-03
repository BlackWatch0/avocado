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
    def __init__(self, _config) -> None:
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        self.stack_id = "cal-stack"
        self.user_id = "cal-user"
        self.new_id = "cal-new"
        self._calendars = [
            CalendarInfo(calendar_id=self.stack_id, name="Avocado Stack Calendar", url=self.stack_id),
            CalendarInfo(calendar_id=self.user_id, name="Avocado User Calendar", url=self.user_id),
            CalendarInfo(calendar_id=self.new_id, name="Avocado New Calendar", url=self.new_id),
        ]
        self._events: dict[str, dict[str, EventRecord]] = {
            self.stack_id: {},
            self.user_id: {
                "uid-1": EventRecord(
                    calendar_id=self.user_id,
                    uid="uid-1",
                    summary="Task 1",
                    description=(
                        "[AI Task]\n"
                        "locked: false\n"
                        "user_intent: move this\n"
                        "[/AI Task]"
                    ),
                    start=now + timedelta(hours=2),
                    end=now + timedelta(hours=3),
                    etag="etag-1",
                ),
                "uid-2": EventRecord(
                    calendar_id=self.user_id,
                    uid="uid-2",
                    summary="Task 2",
                    description=(
                        "[AI Task]\n"
                        "locked: false\n"
                        "user_intent: rename this\n"
                        "[/AI Task]"
                    ),
                    start=now + timedelta(hours=4),
                    end=now + timedelta(hours=5),
                    etag="etag-2",
                ),
            },
            self.new_id: {},
        }

    def list_calendars(self) -> list[CalendarInfo]:
        return [item for item in self._calendars]

    def ensure_managed_calendar(self, calendar_id: str, calendar_name: str) -> CalendarInfo:
        if calendar_id:
            for item in self._calendars:
                if item.calendar_id == calendar_id:
                    return item
        for item in self._calendars:
            if item.name == calendar_name:
                return item
        created = CalendarInfo(calendar_id=(calendar_id or calendar_name), name=calendar_name, url=(calendar_id or calendar_name))
        self._calendars.append(created)
        self._events.setdefault(created.calendar_id, {})
        return created

    def fetch_changes_by_token(self, calendar_id: str, _token: str) -> dict:
        return {
            "supported": True,
            "add_update": [],
            "delete": [],
            "next_token": f"next-{calendar_id}",
        }

    def list_window_index(self, calendar_id: str, _start: datetime, _end: datetime) -> list[dict]:
        rows: list[dict] = []
        for event in self._events.get(calendar_id, {}).values():
            rows.append(
                {
                    "uid": event.uid,
                    "href": event.href or f"{calendar_id}/{event.uid}.ics",
                    "etag": event.etag,
                }
            )
        return rows

    def fetch_events(self, calendar_id: str, _start: datetime, _end: datetime) -> list[EventRecord]:
        return [event.clone() for event in self._events.get(calendar_id, {}).values()]

    def upsert_event(self, calendar_id: str, event: EventRecord, expected_etag: str = "") -> EventRecord:
        current = self._events.setdefault(calendar_id, {}).get(event.uid)
        if expected_etag and current is not None and current.etag and current.etag != expected_etag:
            raise RuntimeError("etag_conflict")
        updated = event.clone()
        updated.calendar_id = calendar_id
        updated.href = updated.href or f"{calendar_id}/{updated.uid}.ics"
        updated.etag = f"{updated.uid}-etag-updated"
        self._events[calendar_id][updated.uid] = updated
        return updated.clone()

    def delete_event(self, calendar_id: str, uid: str, href: str = "") -> bool:
        existed = uid in self._events.get(calendar_id, {})
        self._events.get(calendar_id, {}).pop(uid, None)
        return existed

    def delete_event_with_etag(self, calendar_id: str, uid: str, expected_etag: str = "", href: str = "") -> bool:
        current = self._events.get(calendar_id, {}).get(uid)
        if current is None:
            return True
        if expected_etag and current.etag and current.etag != expected_etag:
            raise RuntimeError("etag_conflict")
        del self._events[calendar_id][uid]
        return True

    def get_event_by_uid(self, calendar_id: str, uid: str) -> EventRecord | None:
        event = self._events.get(calendar_id, {}).get(uid)
        return event.clone() if event else None


class _FakeAIClient:
    def __init__(self, _config) -> None:
        pass

    def is_configured(self) -> bool:
        return True

    def generate_changes(self, *, messages):
        _ = messages
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


class _CountingAIClient:
    calls = 0

    def __init__(self, _config) -> None:
        pass

    def is_configured(self) -> bool:
        return True

    def generate_changes(self, *, messages):
        _ = messages
        _CountingAIClient.calls += 1
        return {"changes": []}


class _ModelCaptureAIClient:
    calls = 0
    models: list[str] = []

    def __init__(self, config) -> None:
        self.config = config
        self.last_usage = {}

    def is_configured(self) -> bool:
        return True

    def generate_changes(self, *, messages):
        _ = messages
        _ModelCaptureAIClient.calls += 1
        _ModelCaptureAIClient.models.append(str(self.config.model))
        return {"changes": []}


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
                        "enabled": True,
                        "base_url": "https://example.test/v1",
                        "api_key": "token",
                        "model": "gpt-test",
                    },
                    "calendar_rules": {
                        "stack_calendar_id": "cal-stack",
                        "user_calendar_id": "cal-user",
                        "new_calendar_id": "cal-new",
                    },
                }
            )
            store = StateStore(str(db_path))
            engine = SyncEngine(manager, store)

            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", _FakeCalDAVService),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient", _FakeAIClient),
            ):
                result = engine.run_once(trigger="manual")

            self.assertEqual(result.status, "success")
            self.assertGreaterEqual(result.conflicts, 1)

            audit_events = store.recent_audit_events(limit=200)
            self.assertTrue(
                any(
                    item["action"] == "conflict"
                    and item["details"].get("reason") == "invalid_datetime"
                    for item in audit_events
                )
            )

            user_uid2 = None
            for mapping in store.list_event_mappings():
                if mapping.get("source") == "user" and mapping.get("source_uid") == "uid-2":
                    user_uid2 = mapping.get("user_uid")
                    break
            self.assertTrue(bool(user_uid2))

    def test_skip_ai_call_when_no_intent_targets(self) -> None:
        class _NoIntentCalDAVService(_FakeCalDAVService):
            def __init__(self, config) -> None:
                super().__init__(config)
                for event in self._events[self.user_id].values():
                    event.description = (
                        "[AI Task]\n"
                        "locked: false\n"
                        "user_intent:\n"
                        "[/AI Task]"
                    )

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
                        "enabled": True,
                        "base_url": "https://example.test/v1",
                        "api_key": "token",
                        "model": "gpt-test",
                    },
                    "calendar_rules": {
                        "stack_calendar_id": "cal-stack",
                        "user_calendar_id": "cal-user",
                        "new_calendar_id": "cal-new",
                    },
                }
            )
            store = StateStore(str(db_path))
            engine = SyncEngine(manager, store)
            _CountingAIClient.calls = 0

            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", _NoIntentCalDAVService),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient", _CountingAIClient),
            ):
                result = engine.run_once(trigger="manual")

            self.assertEqual(result.status, "success")
            self.assertEqual(_CountingAIClient.calls, 0)
            audit_events = store.recent_audit_events(limit=200)
            self.assertTrue(any(item["action"] == "skip_ai_no_targets" for item in audit_events))

    def test_new_calendar_import_triggers_ai_even_without_user_intent(self) -> None:
        class _NewImportCalDAVService(_FakeCalDAVService):
            def __init__(self, config) -> None:
                super().__init__(config)
                now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
                for event in self._events[self.user_id].values():
                    event.description = (
                        "[AI Task]\n"
                        "locked: false\n"
                        "user_intent:\n"
                        "[/AI Task]"
                    )
                self._events[self.new_id]["new-uid-1"] = EventRecord(
                    calendar_id=self.new_id,
                    uid="new-uid-1",
                    summary="Imported New Event",
                    description="new event from intake",
                    start=now + timedelta(hours=6),
                    end=now + timedelta(hours=7),
                    etag="new-etag-1",
                )

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
                        "enabled": True,
                        "base_url": "https://example.test/v1",
                        "api_key": "token",
                        "model": "gpt-test",
                    },
                    "calendar_rules": {
                        "stack_calendar_id": "cal-stack",
                        "user_calendar_id": "cal-user",
                        "new_calendar_id": "cal-new",
                    },
                }
            )
            store = StateStore(str(db_path))
            engine = SyncEngine(manager, store)
            _CountingAIClient.calls = 0

            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", _NewImportCalDAVService),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient", _CountingAIClient),
            ):
                result = engine.run_once(trigger="manual")

            self.assertEqual(result.status, "success")
            self.assertEqual(_CountingAIClient.calls, 1)
            audit_events = store.recent_audit_events(limit=200)
            self.assertTrue(any(item["action"] == "ai_request" for item in audit_events))

    def test_high_load_model_is_used_when_event_count_exceeds_threshold(self) -> None:
        class _ManyEventsCalDAVService(_FakeCalDAVService):
            def __init__(self, config) -> None:
                super().__init__(config)
                now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
                self._events[self.user_id] = {}
                self._events[self.new_id] = {}
                for idx in range(4):
                    uid = f"new-uid-{idx}"
                    self._events[self.new_id][uid] = EventRecord(
                        calendar_id=self.new_id,
                        uid=uid,
                        summary=f"Imported Event {idx}",
                        description="intake item",
                        start=now + timedelta(hours=idx + 2),
                        end=now + timedelta(hours=idx + 3),
                        etag=f"new-etag-{idx}",
                    )

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
                        "enabled": True,
                        "base_url": "https://example.test/v1",
                        "api_key": "token",
                        "model": "gpt-4o-mini",
                        "high_load_model": "gpt-5",
                        "high_load_event_threshold": 3,
                    },
                    "calendar_rules": {
                        "stack_calendar_id": "cal-stack",
                        "user_calendar_id": "cal-user",
                        "new_calendar_id": "cal-new",
                    },
                }
            )
            store = StateStore(str(db_path))
            engine = SyncEngine(manager, store)
            _ModelCaptureAIClient.calls = 0
            _ModelCaptureAIClient.models = []

            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", _ManyEventsCalDAVService),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient", _ModelCaptureAIClient),
            ):
                result = engine.run_once(trigger="manual")

            self.assertEqual(result.status, "success")
            self.assertEqual(_ModelCaptureAIClient.calls, 1)
            self.assertEqual(_ModelCaptureAIClient.models[-1], "gpt-5")
            audit_events = store.recent_audit_events(limit=200)
            ai_request_events = [item for item in audit_events if item["action"] == "ai_request"]
            self.assertTrue(ai_request_events)
            self.assertEqual(ai_request_events[-1]["details"].get("model"), "gpt-5")
            self.assertTrue(bool(ai_request_events[-1]["details"].get("high_load_model_active")))


if __name__ == "__main__":
    unittest.main()

