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
    source_calendar_id = "source-cal"
    stack_calendar_id = "stack-cal"
    user_calendar_id = "user-cal"
    new_calendar_id = "new-cal"

    def __init__(self, _config: object) -> None:
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        self.events_by_calendar = {
            self.source_calendar_id: {
                "source-uid": EventRecord(
                    calendar_id=self.source_calendar_id,
                    uid="source-uid",
                    summary="Source Event",
                    description=(
                        "Original source description\n\n"
                        "[AI Task]\n"
                        "locked: false\n"
                        "editable_fields:\n"
                        "  - start\n"
                        "  - end\n"
                        "  - summary\n"
                        "  - location\n"
                        "  - description\n"
                        "user_intent: move earlier by 30 minutes\n"
                        "[/AI Task]"
                    ),
                    start=now + timedelta(hours=2),
                    end=now + timedelta(hours=3),
                    etag="src-etag",
                )
            },
            self.stack_calendar_id: {},
            self.user_calendar_id: {},
            self.new_calendar_id: {},
        }

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


class AIRequestAuditTests(unittest.TestCase):
    def test_run_once_records_ai_request_tokens(self) -> None:
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
                    "ai": {
                        "enabled": True,
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "test-key",
                        "model": "gpt-4o-mini",
                    },
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
            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", return_value=fake_service),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient") as ai_client_cls,
            ):
                ai_client = ai_client_cls.return_value
                ai_client.is_configured.return_value = True
                ai_client.generate_changes.return_value = {"changes": []}
                ai_client.last_usage = {
                    "prompt_tokens": 101,
                    "completion_tokens": 22,
                    "total_tokens": 123,
                }
                engine = SyncEngine(manager, state_store)
                result = engine.run_once(trigger="manual")
            self.assertEqual(result.status, "success")
            points = state_store.ai_request_bytes_series(days=30, limit=100)
            self.assertGreaterEqual(len(points), 1)
            self.assertGreater(points[-1]["request_tokens"], 0)

    def test_second_run_does_not_retrigger_after_ai_time_change(self) -> None:
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
                    "ai": {
                        "enabled": True,
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "test-key",
                        "model": "gpt-4o-mini",
                    },
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
            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", return_value=fake_service),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient") as ai_client_cls,
            ):
                ai_client = ai_client_cls.return_value
                ai_client.is_configured.return_value = True

                source_event = fake_service.events_by_calendar[_FakeCalDAVService.source_calendar_id]["source-uid"]
                new_start = source_event.start - timedelta(minutes=30)
                new_end = source_event.end - timedelta(minutes=30)
                ai_client.last_usage = {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                }
                calls = {"count": 0}
                captured_payloads: list[dict] = []

                def _generate_changes(*, messages):
                    calls["count"] += 1
                    user_payload = {}
                    for msg in messages:
                        if str(msg.get("role", "")) == "user":
                            try:
                                user_payload = json.loads(str(msg.get("content", "")))
                            except Exception:
                                user_payload = {}
                            break
                    if isinstance(user_payload, dict):
                        captured_payloads.append(user_payload)
                    target_uids = user_payload.get("target_uids", []) if isinstance(user_payload, dict) else []
                    target_uid = str((target_uids[0] if target_uids else "") or "").strip()
                    return {
                        "changes": [
                            {
                                "uid": target_uid,
                                "start": new_start.isoformat(),
                                "end": new_end.isoformat(),
                                "reason": "postpone 30 minutes",
                            }
                        ]
                    }

                ai_client.generate_changes.side_effect = _generate_changes

                engine = SyncEngine(manager, state_store)
                first_result = engine.run_once(trigger="manual")
                self.assertEqual(first_result.status, "success")

                second_result = engine.run_once(trigger="manual")
                self.assertEqual(second_result.status, "success")
                self.assertEqual(calls["count"], 1)
                self.assertGreaterEqual(len(captured_payloads), 1)
                first_payload = captured_payloads[0]
                payload_events = first_payload.get("events_by_uid", {})
                self.assertIsInstance(payload_events, dict)
                self.assertGreaterEqual(len(payload_events), 1)
                target_uids = first_payload.get("target_uids", [])
                self.assertIsInstance(target_uids, list)
                self.assertGreaterEqual(len(target_uids), 1)
                first_target_uid = str(target_uids[0] or "").strip()
                self.assertIn(first_target_uid, payload_events)
                first_event = payload_events[first_target_uid] or {}
                self.assertIn("time_range", first_event)
                self.assertIn("summary", first_event)
                self.assertIn("locked", first_event)
                self.assertNotIn("calendar_id", first_event)
                self.assertNotIn("x-version", first_event)
                self.assertNotIn("x-editable_fields", first_event)
                self.assertNotIn("x-updated_at", first_event)
                self.assertNotIn("[AI Task]", str(first_event.get("description", "")))

                user_events = list(fake_service.events_by_calendar[_FakeCalDAVService.user_calendar_id].values())
                self.assertGreaterEqual(len(user_events), 1)
                self.assertIn("user_intent: ''", user_events[0].description or "")

    def test_sparse_context_applies_to_all_targets_scope_for_user_intent_events(self) -> None:
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
                    "ai": {
                        "enabled": True,
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "test-key",
                        "model": "gpt-4o-mini",
                        "sparse_new_event_context_enabled": True,
                        "sparse_context_scope": "all_targets",
                        "sparse_new_event_neighbor_count": 0,
                        "payload_target_description_max_chars": 20,
                        "payload_neighbor_description_max_chars": 5,
                        "payload_max_full_detail_events": 1,
                    },
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
            now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            fake_service.events_by_calendar[_FakeCalDAVService.source_calendar_id]["source-uid-2"] = EventRecord(
                calendar_id=_FakeCalDAVService.source_calendar_id,
                uid="source-uid-2",
                summary="Another Event",
                description="neighbor detail should be busy only in sparse mode",
                start=now + timedelta(hours=4),
                end=now + timedelta(hours=5),
                etag="src2-etag",
            )
            state_store.upsert_event_mapping(
                sync_id="sync-source-uid-2",
                source="ext",
                source_calendar_id=_FakeCalDAVService.source_calendar_id,
                source_uid="source-uid-2",
                source_href_hash="",
                user_uid="user-source-uid-2",
                stack_uid="avo-source-uid-2",
                status="active",
            )
            captured_payloads: list[dict] = []
            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", return_value=fake_service),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient") as ai_client_cls,
            ):
                ai_client = ai_client_cls.return_value
                ai_client.is_configured.return_value = True
                ai_client.last_usage = {"prompt_tokens": 33, "completion_tokens": 7, "total_tokens": 40}

                def _generate_changes(*, messages):
                    payload = {}
                    for msg in messages:
                        if str(msg.get("role", "")) == "user":
                            payload = json.loads(str(msg.get("content", "")))
                            break
                    captured_payloads.append(payload)
                    return {"changes": [], "creates": []}

                ai_client.generate_changes.side_effect = _generate_changes
                engine = SyncEngine(manager, state_store)
                result = engine.run_once(trigger="manual")

            self.assertEqual(result.status, "success")
            self.assertGreaterEqual(len(captured_payloads), 1)
            payload = captured_payloads[0]
            self.assertEqual(payload.get("planning_phase"), "phase1")
            self.assertEqual(payload.get("context_strategy"), "target_neighbors_full_others_busy")
            target_uids = payload.get("target_uids", [])
            self.assertTrue(target_uids)
            target_uid = str(target_uids[0] or "")
            events_by_uid = payload.get("events_by_uid", {})
            self.assertIn(target_uid, events_by_uid)
            target_item = events_by_uid.get(target_uid, {})
            self.assertEqual(target_item.get("detail_level"), "full")
            self.assertLessEqual(len(str(target_item.get("description", ""))), 20)
            self.assertIn("user_intent", target_item)
            target_uid_set = {str(item or "") for item in target_uids}
            non_target_uids = [uid for uid in events_by_uid.keys() if uid not in target_uid_set]
            self.assertTrue(non_target_uids)
            busy_item = events_by_uid.get(non_target_uids[0], {})
            self.assertEqual(busy_item.get("detail_level"), "busy")
            self.assertNotIn("description", busy_item)
            self.assertNotIn("location", busy_item)

            audit_events = state_store.recent_audit_events(limit=200)
            ai_request_events = [item for item in audit_events if item["action"] == "ai_request"]
            self.assertTrue(ai_request_events)
            details = ai_request_events[-1]["details"]
            self.assertEqual(details.get("sparse_context_scope"), "all_targets")
            self.assertGreaterEqual(int(details.get("full_detail_events_count", 0)), 1)
            self.assertGreaterEqual(int(details.get("busy_events_count", 0)), 1)

    def test_new_event_sparse_phase_triggers_context_then_second_call(self) -> None:
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
                    "ai": {
                        "enabled": True,
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "test-key",
                        "model": "gpt-4o-mini",
                        "sparse_new_event_context_enabled": True,
                        "sparse_new_event_neighbor_count": 0,
                        "sparse_new_event_max_context_requests": 2,
                    },
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
            now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            fake_service.events_by_calendar[_FakeCalDAVService.new_calendar_id]["new-uid"] = EventRecord(
                calendar_id=_FakeCalDAVService.new_calendar_id,
                uid="new-uid",
                summary="New Inbox Event",
                description="new",
                start=now + timedelta(hours=8),
                end=now + timedelta(hours=9),
                etag="new-etag",
            )
            fake_service.events_by_calendar[_FakeCalDAVService.source_calendar_id]["source-uid-2"] = EventRecord(
                calendar_id=_FakeCalDAVService.source_calendar_id,
                uid="source-uid-2",
                summary="Busy context event",
                description="context",
                start=now + timedelta(hours=15),
                end=now + timedelta(hours=16),
                etag="src2-etag",
            )
            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", return_value=fake_service),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient") as ai_client_cls,
            ):
                ai_client = ai_client_cls.return_value
                ai_client.is_configured.return_value = True
                ai_client.last_usage = {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}

                captured_payloads: list[dict] = []
                calls = {"count": 0}

                def _generate_changes(*, messages):
                    calls["count"] += 1
                    user_payload = {}
                    for msg in messages:
                        if str(msg.get("role", "")) == "user":
                            user_payload = json.loads(str(msg.get("content", "")))
                            break
                    captured_payloads.append(user_payload)
                    if calls["count"] == 1:
                        return {
                            "changes": [],
                            "creates": [],
                            "context_requests": [{"date": now.date().isoformat(), "reason": "need details"}],
                        }
                    target_uids = user_payload.get("target_uids", [])
                    target_uid = str((target_uids[0] if target_uids else "") or "").strip()
                    return {
                        "changes": [
                            {
                                "uid": target_uid,
                                "start": (now + timedelta(hours=9)).isoformat(),
                                "end": (now + timedelta(hours=10)).isoformat(),
                                "reason": "scheduled with full context",
                            }
                        ]
                    }

                ai_client.generate_changes.side_effect = _generate_changes
                engine = SyncEngine(manager, state_store)
                result = engine.run_once(trigger="manual")
            self.assertEqual(result.status, "success")
            self.assertEqual(calls["count"], 2)
            self.assertGreaterEqual(len(captured_payloads), 2)
            phase1 = captured_payloads[0]
            phase2 = captured_payloads[1]
            self.assertEqual(phase1.get("planning_phase"), "phase1")
            self.assertEqual(phase2.get("planning_phase"), "phase2")
            events_phase1 = phase1.get("events_by_uid", {})
            self.assertIsInstance(events_phase1, dict)
            self.assertGreaterEqual(len(events_phase1), 1)
            busy_items = [item for item in events_phase1.values() if isinstance(item, dict) and item.get("detail_level") == "busy"]
            for item in busy_items:
                self.assertNotIn("location", item)
                self.assertNotIn("description", item)
            self.assertIn("requested_context", phase2)

    def test_sparse_phase_forces_second_call_when_phase1_edits_non_target_without_context(self) -> None:
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
                    "ai": {
                        "enabled": True,
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "test-key",
                        "model": "gpt-4o-mini",
                        "sparse_new_event_context_enabled": True,
                        "sparse_new_event_neighbor_count": 0,
                        "sparse_new_event_max_context_requests": 3,
                    },
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
            now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            fake_service.events_by_calendar[_FakeCalDAVService.new_calendar_id]["new-uid"] = EventRecord(
                calendar_id=_FakeCalDAVService.new_calendar_id,
                uid="new-uid",
                summary="New Inbox Event",
                description="new",
                start=now + timedelta(hours=8),
                end=now + timedelta(hours=9),
                etag="new-etag",
            )
            fake_service.events_by_calendar[_FakeCalDAVService.source_calendar_id]["other-uid"] = EventRecord(
                calendar_id=_FakeCalDAVService.source_calendar_id,
                uid="other-uid",
                summary="Other Event",
                description="other",
                start=now + timedelta(hours=12),
                end=now + timedelta(hours=13),
                etag="other-etag",
            )
            with (
                mock.patch("avocado.sync.pipeline.CalDAVService", return_value=fake_service),
                mock.patch("avocado.sync.pipeline.OpenAICompatibleClient") as ai_client_cls,
            ):
                ai_client = ai_client_cls.return_value
                ai_client.is_configured.return_value = True
                ai_client.last_usage = {"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48}
                captured_payloads: list[dict] = []
                calls = {"count": 0}

                def _generate_changes(*, messages):
                    calls["count"] += 1
                    payload = {}
                    for msg in messages:
                        if str(msg.get("role", "")) == "user":
                            payload = json.loads(str(msg.get("content", "")))
                            break
                    captured_payloads.append(payload)
                    target_uids = payload.get("target_uids", []) if isinstance(payload, dict) else []
                    target_uid = str((target_uids[0] if target_uids else "") or "").strip()
                    if calls["count"] == 1:
                        other_uid = ""
                        events_by_uid = payload.get("events_by_uid", {}) if isinstance(payload, dict) else {}
                        for uid in (events_by_uid.keys() if isinstance(events_by_uid, dict) else []):
                            uid_text = str(uid or "").strip()
                            if uid_text and uid_text != target_uid:
                                other_uid = uid_text
                                break
                        return {
                            "changes": [
                                {
                                    "uid": target_uid,
                                    "start": (now + timedelta(days=1, hours=9)).isoformat(),
                                    "end": (now + timedelta(days=1, hours=10)).isoformat(),
                                    "reason": "move target",
                                },
                                {
                                    "uid": other_uid,
                                    "start": (now + timedelta(days=1, hours=11)).isoformat(),
                                    "end": (now + timedelta(days=1, hours=12)).isoformat(),
                                    "reason": "also move other",
                                },
                            ],
                            "creates": [],
                        }
                    return {"changes": [], "creates": []}

                ai_client.generate_changes.side_effect = _generate_changes
                engine = SyncEngine(manager, state_store)
                result = engine.run_once(trigger="manual")
            self.assertEqual(result.status, "success")
            self.assertEqual(calls["count"], 2)
            self.assertGreaterEqual(len(captured_payloads), 2)
            self.assertEqual(captured_payloads[0].get("planning_phase"), "phase1")
            self.assertEqual(captured_payloads[1].get("planning_phase"), "phase2")
            self.assertTrue(bool(captured_payloads[1].get("requested_context")))


if __name__ == "__main__":
    unittest.main()
