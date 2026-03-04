import json
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
    service_tiers: list[str] = []

    def __init__(self, config) -> None:
        self.config = config
        self.last_usage = {}

    def is_configured(self) -> bool:
        return True

    def generate_changes(self, *, messages):
        _ = messages
        _ModelCaptureAIClient.calls += 1
        _ModelCaptureAIClient.models.append(str(self.config.model))
        _ModelCaptureAIClient.service_tiers.append(str(getattr(self.config, "_request_service_tier", "")))
        return {"changes": []}


class _MoveOutWindowAIClient:
    calls = 0

    def __init__(self, _config) -> None:
        self.last_usage = {}

    def is_configured(self) -> bool:
        return True

    def generate_changes(self, *, messages):
        _ = messages
        _MoveOutWindowAIClient.calls += 1
        return {
            "changes": [
                {
                    "calendar_id": "cal-user",
                    "uid": "uid-1",
                    "start": "2030-01-01T10:00:00+00:00",
                    "end": "2030-01-01T11:00:00+00:00",
                    "reason": "move out of current planning window",
                }
            ]
        }


class _SplitCreateAIClient:
    calls = 0

    def __init__(self, _config) -> None:
        self.last_usage = {}

    def is_configured(self) -> bool:
        return True

    def generate_changes(self, *, messages):
        _SplitCreateAIClient.calls += 1
        user_payload: dict[str, object] = {}
        for msg in messages:
            if str(msg.get("role", "")) != "user":
                continue
            try:
                user_payload = json.loads(str(msg.get("content", "")))
            except Exception:
                user_payload = {}
            break
        target_uids = user_payload.get("target_uids", []) if isinstance(user_payload, dict) else []
        target_uid = str((target_uids[0] if isinstance(target_uids, list) and target_uids else "") or "").strip()
        events_by_uid = user_payload.get("events_by_uid", {}) if isinstance(user_payload, dict) else {}
        event_payload = events_by_uid.get(target_uid, {}) if isinstance(events_by_uid, dict) else {}
        event_range = event_payload.get("t", []) if isinstance(event_payload, dict) else []
        if not target_uid or not isinstance(event_range, list) or len(event_range) < 2:
            return {"changes": [], "creates": []}
        source_start = datetime.fromisoformat(str(event_range[0]))
        first_end = source_start + timedelta(minutes=30)
        second_start = source_start + timedelta(hours=1)
        second_end = source_start + timedelta(hours=2)
        return {
            "changes": [
                {
                    "uid": target_uid,
                    "start": source_start.isoformat(),
                    "end": first_end.isoformat(),
                    "reason": "split part 1",
                }
            ],
            "creates": [
                {
                    "from_uid": target_uid,
                    "create_key": "split-2",
                    "start": second_start.isoformat(),
                    "end": second_end.isoformat(),
                    "summary": "Task 1 (2/2)",
                    "description": "Continuation block",
                    "reason": "split part 2",
                }
            ],
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

    def test_new_calendar_mapped_but_not_cleaned_still_imports_and_triggers_ai(self) -> None:
        class _MappedNewImportCalDAVService(_FakeCalDAVService):
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
                self._events[self.new_id] = {
                    "new-stuck-uid": EventRecord(
                        calendar_id=self.new_id,
                        uid="new-stuck-uid",
                        summary="Stuck Intake Event",
                        description="intake retained after interrupted run",
                        start=now + timedelta(hours=8),
                        end=now + timedelta(hours=9),
                        etag="new-stuck-etag",
                    )
                }

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
            store.upsert_event_mapping(
                sync_id="sync-pre-mapped-new",
                source="new",
                source_calendar_id="cal-new",
                source_uid="new-stuck-uid",
                source_href_hash="pre-hash",
                user_uid="avo-sync-pre-mapped-new",
                stack_uid="avo-sync-pre-mapped-new",
                status="active",
            )
            engine = SyncEngine(manager, store)
            _CountingAIClient.calls = 0

            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", _MappedNewImportCalDAVService),
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
            _ModelCaptureAIClient.service_tiers = []

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

    def test_high_load_flex_tier_is_enabled_by_switch(self) -> None:
        class _ManyEventsCalDAVService(_FakeCalDAVService):
            def __init__(self, config) -> None:
                super().__init__(config)
                now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
                self._events[self.user_id] = {}
                self._events[self.new_id] = {}
                for idx in range(4):
                    uid = f"new-flex-uid-{idx}"
                    self._events[self.new_id][uid] = EventRecord(
                        calendar_id=self.new_id,
                        uid=uid,
                        summary=f"Imported Flex Event {idx}",
                        description="intake item",
                        start=now + timedelta(hours=idx + 2),
                        end=now + timedelta(hours=idx + 3),
                        etag=f"new-flex-etag-{idx}",
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
                        "high_load_use_flex": True,
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
            _ModelCaptureAIClient.service_tiers = []

            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", _ManyEventsCalDAVService),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient", _ModelCaptureAIClient),
            ):
                result = engine.run_once(trigger="manual")

            self.assertEqual(result.status, "success")
            self.assertEqual(_ModelCaptureAIClient.calls, 1)
            self.assertEqual(_ModelCaptureAIClient.models[-1], "gpt-5")
            self.assertEqual(_ModelCaptureAIClient.service_tiers[-1], "flex")
            audit_events = store.recent_audit_events(limit=200)
            ai_request_events = [item for item in audit_events if item["action"] == "ai_request"]
            self.assertTrue(ai_request_events)
            self.assertEqual(ai_request_events[-1]["details"].get("service_tier"), "flex")

    def test_high_load_auto_scoring_can_activate_model_and_flex(self) -> None:
        class _DenseEventsCalDAVService(_FakeCalDAVService):
            def __init__(self, config) -> None:
                super().__init__(config)
                now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
                self._events[self.user_id] = {
                    "uid-auto-1": EventRecord(
                        calendar_id=self.user_id,
                        uid="uid-auto-1",
                        summary="Auto Task 1",
                        description=(
                            "[AI Task]\n"
                            "locked: false\n"
                            "user_intent: optimize\n"
                            "[/AI Task]"
                        ),
                        start=now + timedelta(hours=2),
                        end=now + timedelta(hours=4),
                        etag="etag-auto-1",
                    ),
                    "uid-auto-2": EventRecord(
                        calendar_id=self.user_id,
                        uid="uid-auto-2",
                        summary="Auto Task 2",
                        description=(
                            "[AI Task]\n"
                            "locked: false\n"
                            "user_intent: optimize\n"
                            "[/AI Task]"
                        ),
                        start=now + timedelta(hours=3),
                        end=now + timedelta(hours=5),
                        etag="etag-auto-2",
                    ),
                }
                self._events[self.new_id] = {}

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
                        "high_load_event_threshold": 0,
                        "high_load_auto_enabled": True,
                        "high_load_auto_score_threshold": 0.3,
                        "high_load_auto_event_baseline": 2,
                        "high_load_use_flex": True,
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
            _ModelCaptureAIClient.service_tiers = []

            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", _DenseEventsCalDAVService),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient", _ModelCaptureAIClient),
            ):
                result = engine.run_once(trigger="manual")

            self.assertEqual(result.status, "success")
            self.assertEqual(_ModelCaptureAIClient.calls, 1)
            self.assertEqual(_ModelCaptureAIClient.models[-1], "gpt-5")
            self.assertEqual(_ModelCaptureAIClient.service_tiers[-1], "flex")
            audit_events = store.recent_audit_events(limit=200)
            ai_request_events = [item for item in audit_events if item["action"] == "ai_request"]
            self.assertTrue(ai_request_events)
            details = ai_request_events[-1]["details"]
            self.assertFalse(bool(details.get("high_load_manual_active")))
            self.assertTrue(bool(details.get("high_load_auto_enabled")))
            self.assertTrue(bool(details.get("high_load_auto_active")))
            self.assertGreaterEqual(float(details.get("high_load_auto_score", 0.0)), 0.3)

    def test_external_calendar_new_import_triggers_ai_without_intent(self) -> None:
        class _ExternalImportCalDAVService(_FakeCalDAVService):
            def __init__(self, config) -> None:
                super().__init__(config)
                self.ext_id = "cal-ext"
                self._calendars.append(
                    CalendarInfo(calendar_id=self.ext_id, name="Personal", url=self.ext_id)
                )
                now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
                self._events[self.user_id] = {}
                self._events[self.new_id] = {}
                self._events[self.ext_id] = {
                    "ext-uid-1": EventRecord(
                        calendar_id=self.ext_id,
                        uid="ext-uid-1",
                        summary="External Imported Event",
                        description="from personal calendar",
                        start=now + timedelta(hours=6),
                        end=now + timedelta(hours=7),
                        etag="ext-etag-1",
                    )
                }

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
                mock.patch("avocado.sync.pipeline.CalDAVService", _ExternalImportCalDAVService),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient", _CountingAIClient),
            ):
                result = engine.run_once(trigger="manual")

            self.assertEqual(result.status, "success")
            self.assertEqual(_CountingAIClient.calls, 1)
            audit_events = store.recent_audit_events(limit=200)
            self.assertTrue(any(item["action"] == "ai_request" for item in audit_events))

    def test_ai_moved_event_outside_window_still_writes_back(self) -> None:
        class _WindowFilteringCalDAVService(_FakeCalDAVService):
            def fetch_events(self, calendar_id: str, start: datetime, end: datetime) -> list[EventRecord]:
                items = []
                for event in self._events.get(calendar_id, {}).values():
                    if event.start is None or event.end is None:
                        continue
                    if event.end <= start or event.start >= end:
                        continue
                    items.append(event.clone())
                return items

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
                    "sync": {
                        "window_days": 1,
                        "interval_seconds": 300,
                        "timezone": "UTC",
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
            _MoveOutWindowAIClient.calls = 0

            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", _WindowFilteringCalDAVService),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient", _MoveOutWindowAIClient),
            ):
                result = engine.run_once(trigger="manual")

            self.assertEqual(result.status, "success")
            self.assertEqual(_MoveOutWindowAIClient.calls, 1)
            mappings = store.list_event_mappings()
            uid1_mapping = next(item for item in mappings if str(item.get("source_uid")) == "uid-1")
            user_uid = str(uid1_mapping.get("user_uid", ""))
            stack_uid = str(uid1_mapping.get("stack_uid", ""))
            audit_events = store.recent_audit_events(limit=300)
            apply_events = [item for item in audit_events if item["action"] == "apply_ai_change"]
            self.assertTrue(apply_events)
            after_event = apply_events[-1]["details"].get("after_event", {})
            self.assertIn(str(after_event.get("uid", "")), {stack_uid, user_uid, "uid-1"})
            self.assertEqual(str(after_event.get("start")), "2030-01-01T10:00:00+00:00")

    def test_ai_creates_are_idempotent_with_deterministic_source_uid(self) -> None:
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
            fake_service = _FakeCalDAVService(object())
            _SplitCreateAIClient.calls = 0

            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", return_value=fake_service),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient", _SplitCreateAIClient),
            ):
                first = engine.run_once(trigger="manual")
                self.assertEqual(first.status, "success")
                source_mapping = next(
                    item for item in store.list_event_mappings() if str(item.get("source_uid", "")) == "uid-1"
                )
                source_user_uid = str(source_mapping.get("user_uid", ""))
                for uid, event in fake_service._events[fake_service.user_id].items():
                    if uid == source_user_uid:
                        event.description = "[AI Task]\nlocked: false\nuser_intent: split again\n[/AI Task]"
                    else:
                        event.description = "[AI Task]\nlocked: false\nuser_intent: ''\n[/AI Task]"
                store.set_meta("last_applied_ai_hash", "force-replan")
                second = engine.run_once(trigger="manual")
                self.assertEqual(second.status, "success")

            self.assertGreaterEqual(_SplitCreateAIClient.calls, 2)
            mappings = store.list_event_mappings()
            ai_mappings = [item for item in mappings if str(item.get("source", "")) == "ai"]
            self.assertEqual(len(ai_mappings), 1)
            ai_mapping = ai_mappings[0]
            stack_uid = str(ai_mapping.get("stack_uid", ""))
            user_uid = str(ai_mapping.get("user_uid", ""))
            self.assertIn(stack_uid, fake_service._events[fake_service.stack_id])
            self.assertIn(user_uid, fake_service._events[fake_service.user_id])
            stack_split_events = [
                event for event in fake_service._events[fake_service.stack_id].values() if event.summary == "Task 1 (2/2)"
            ]
            user_split_events = [
                event for event in fake_service._events[fake_service.user_id].values() if event.summary == "Task 1 (2/2)"
            ]
            self.assertEqual(len(stack_split_events), 1)
            self.assertEqual(len(user_split_events), 1)


if __name__ == "__main__":
    unittest.main()
