import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from avocado.models import SyncResult
from avocado.web_admin import create_app


class WebAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = str(Path(self.temp_dir.name) / "config.yaml")
        self.state_path = str(Path(self.temp_dir.name) / "state.db")
        os.environ["AVOCADO_CONFIG_PATH"] = self.config_path
        os.environ["AVOCADO_STATE_PATH"] = self.state_path
        self.client = TestClient(create_app())

        # Seed non-empty secrets for masking/preserve tests.
        seed_payload = {
            "caldav": {"base_url": "https://dav.example.com", "username": "u", "password": "secret-pass"},
            "ai": {"base_url": "https://api.example.com/v1", "api_key": "secret-key", "model": "gpt-4o-mini"},
            "sync": {"window_days": 7, "interval_seconds": 300, "timezone": "UTC"},
            "calendar_rules": {
                "immutable_keywords": ["fixed"],
                "immutable_calendar_ids": ["cal-1"],
                "staging_calendar_id": "stage-id",
                "staging_calendar_name": "stage",
                "intake_calendar_id": "intake-id",
                "intake_calendar_name": "intake",
            },
            "task_defaults": {"locked": False, "mandatory": False, "editable_fields": ["start", "end"]},
        }
        resp = self.client.put("/api/config", json={"payload": seed_payload})
        self.assertEqual(resp.status_code, 200)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_root_admin_page(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Avocado Admin", resp.text)

    def test_config_raw_has_masked_meta(self) -> None:
        resp = self.client.get("/api/config/raw")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["config"]["caldav"]["password"], "***")
        self.assertEqual(data["config"]["ai"]["api_key"], "***")
        self.assertTrue(data["meta"]["caldav"]["password"]["is_masked"])
        self.assertTrue(data["meta"]["ai"]["api_key"]["is_masked"])

    def test_put_config_empty_secret_does_not_override(self) -> None:
        update = {
            "caldav": {"base_url": "https://dav-2.example.com", "password": ""},
            "ai": {"model": "gpt-4.1", "api_key": ""},
        }
        resp = self.client.put("/api/config", json={"payload": update})
        self.assertEqual(resp.status_code, 200)
        config = resp.json()["config"]
        self.assertEqual(config["caldav"]["base_url"], "https://dav-2.example.com")
        self.assertEqual(config["caldav"]["password"], "secret-pass")
        self.assertEqual(config["ai"]["api_key"], "secret-key")
        self.assertEqual(config["ai"]["model"], "gpt-4.1")

    def test_put_config_masked_secret_does_not_override(self) -> None:
        update = {"caldav": {"password": "***"}, "ai": {"api_key": "***"}}
        resp = self.client.put("/api/config", json={"payload": update})
        self.assertEqual(resp.status_code, 200)
        config = resp.json()["config"]
        self.assertEqual(config["caldav"]["password"], "secret-pass")
        self.assertEqual(config["ai"]["api_key"], "secret-key")

    def test_put_config_non_secret_fields_merge(self) -> None:
        update = {"sync": {"interval_seconds": 600}}
        resp = self.client.put("/api/config", json={"payload": update})
        self.assertEqual(resp.status_code, 200)
        config = resp.json()["config"]
        self.assertEqual(config["sync"]["interval_seconds"], 600)
        self.assertEqual(config["sync"]["window_days"], 7)

    def test_put_config_per_calendar_defaults_persist(self) -> None:
        update = {
            "calendar_rules": {
                "per_calendar_defaults": {
                    "cal-1": {"mode": "immutable", "locked": True, "mandatory": True},
                    "cal-2": {"mode": "editable", "locked": False, "mandatory": True},
                }
            }
        }
        resp = self.client.put("/api/config", json={"payload": update})
        self.assertEqual(resp.status_code, 200)
        rules = resp.json()["config"]["calendar_rules"]
        self.assertIn("cal-1", rules["per_calendar_defaults"])
        self.assertEqual(rules["per_calendar_defaults"]["cal-1"]["mode"], "immutable")
        self.assertTrue(rules["per_calendar_defaults"]["cal-1"]["locked"])

    def test_ai_connectivity_api(self) -> None:
        with mock.patch(
            "avocado.web_admin.OpenAICompatibleClient.test_connectivity",
            return_value=(True, "Connected. Model response: OK"),
        ), mock.patch(
            "avocado.web_admin.OpenAICompatibleClient.list_models",
            return_value=["gpt-4o-mini", "gpt-4.1-mini"],
        ):
            resp = self.client.post("/api/ai/test")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("Connected", data["message"])
        self.assertEqual(data["models"], ["gpt-4o-mini", "gpt-4.1-mini"])

    def test_calendars_marks_managed_duplicates(self) -> None:
        update = {
            "calendar_rules": {
                "staging_calendar_id": "stage-id",
                "staging_calendar_name": "Avocado AI Staging",
                "user_calendar_id": "user-id",
                "user_calendar_name": "Avocado User Calendar",
                "intake_calendar_id": "intake-id",
                "intake_calendar_name": "Avocado New Events",
            }
        }
        resp = self.client.put("/api/config", json={"payload": update})
        self.assertEqual(resp.status_code, 200)

        class _FakeService:
            def __init__(self, _config: object) -> None:
                pass

            def ensure_staging_calendar(self, calendar_id: str, calendar_name: str) -> object:
                return type(
                    "CalendarInfoObj",
                    (),
                    {
                        "calendar_id": calendar_id,
                        "name": calendar_name,
                        "url": calendar_id,
                        "to_dict": lambda self: {
                            "calendar_id": self.calendar_id,
                            "name": self.name,
                            "url": self.url,
                            "immutable_suggested": False,
                        },
                    },
                )()

            def list_calendars(self) -> list[object]:
                def _cal(cid: str, name: str) -> object:
                    return type(
                        "CalendarInfoObj",
                        (),
                        {
                            "calendar_id": cid,
                            "name": name,
                            "url": cid,
                            "to_dict": lambda self: {
                                "calendar_id": self.calendar_id,
                                "name": self.name,
                                "url": self.url,
                                "immutable_suggested": False,
                            },
                        },
                    )()

                return [
                    _cal("stage-id", "Avocado AI Staging"),
                    _cal("user-id", "Avocado User Calendar"),
                    _cal("intake-id", "Avocado New Events"),
                    _cal("dup-user-id", "Avocado User Calendar"),
                    _cal("dup-intake-id", "Avocado New Events"),
                    _cal("normal-id", "Personal"),
                ]

            def suggest_immutable_calendar_ids(self, calendars: list[object], keywords: list[str]) -> set[str]:
                return set()

        with mock.patch("avocado.web_admin.CalDAVService", _FakeService):
            resp = self.client.get("/api/calendars")

        self.assertEqual(resp.status_code, 200)
        rows = resp.json()["calendars"]
        duplicate_rows = [x for x in rows if x["calendar_id"] == "dup-user-id"]
        self.assertEqual(len(duplicate_rows), 1)
        self.assertTrue(duplicate_rows[0]["managed_duplicate"])
        self.assertEqual(duplicate_rows[0]["managed_duplicate_role"], "user")
        duplicate_intake_rows = [x for x in rows if x["calendar_id"] == "dup-intake-id"]
        self.assertEqual(len(duplicate_intake_rows), 1)
        self.assertTrue(duplicate_intake_rows[0]["managed_duplicate"])
        self.assertEqual(duplicate_intake_rows[0]["managed_duplicate_role"], "intake")

    def test_sync_run_window_calls_sync_engine(self) -> None:
        fake_result = SyncResult(
            status="success",
            message="ok",
            duration_ms=42,
            changes_applied=1,
            conflicts=0,
            trigger="manual-window",
            run_at=datetime(2026, 2, 27, 0, 0, 0, tzinfo=timezone.utc),
        )
        with mock.patch.object(self.client.app.state.context.sync_engine, "run_once", return_value=fake_result) as run_once:
            resp = self.client.post(
                "/api/sync/run-window",
                json={
                    "start": "2026-03-01T00:00:00Z",
                    "end": "2026-03-03T23:59:59Z",
                },
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["result"]["status"], "success")
        run_once.assert_called_once()

    def test_sync_run_window_rejects_invalid_range(self) -> None:
        resp = self.client.post(
            "/api/sync/run-window",
            json={
                "start": "2026-03-03T00:00:00Z",
                "end": "2026-03-01T23:59:59Z",
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_ai_changes_list_from_audit(self) -> None:
        self.client.app.state.context.state_store.record_audit_event(
            calendar_id="user-id",
            uid="uid-1",
            action="apply_ai_change",
            details={
                "reason": "move before dinner",
                "title": "Training",
                "start": "2026-03-05T15:00:00+00:00",
                "end": "2026-03-05T16:00:00+00:00",
                "fields": ["start", "end"],
                "patch": [{"field": "start", "before": "2026-03-05T19:00:00+00:00", "after": "2026-03-05T15:00:00+00:00"}],
                "before_event": {"calendar_id": "user-id", "uid": "uid-1"},
                "after_event": {"calendar_id": "user-id", "uid": "uid-1"},
            },
        )
        resp = self.client.get("/api/ai/changes?limit=10")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["changes"]
        self.assertTrue(len(items) >= 1)
        self.assertEqual(items[0]["uid"], "uid-1")

    def test_ai_changes_reason_fallback_from_fields(self) -> None:
        self.client.app.state.context.state_store.record_audit_event(
            calendar_id="user-id",
            uid="uid-reason",
            action="apply_ai_change",
            details={
                "reason": "",
                "fields": ["start", "end"],
                "patch": [
                    {"field": "start", "before": "2026-03-05T10:00:00+00:00", "after": "2026-03-05T11:00:00+00:00"}
                ],
            },
        )
        resp = self.client.get("/api/ai/changes?limit=10")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["changes"]
        target = next((x for x in items if x["uid"] == "uid-reason"), None)
        self.assertIsNotNone(target)
        self.assertIn("AI adjusted fields", target["reason"])

    def test_ai_changes_legacy_without_patch_is_hidden(self) -> None:
        self.client.app.state.context.state_store.record_audit_event(
            calendar_id="user-id",
            uid="uid-legacy",
            action="apply_ai_change",
            details={},
        )
        resp = self.client.get("/api/ai/changes?limit=10")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["changes"]
        target = next((x for x in items if x["uid"] == "uid-legacy"), None)
        self.assertIsNone(target)

    def test_undo_ai_change(self) -> None:
        self.client.app.state.context.state_store.record_audit_event(
            calendar_id="user-id",
            uid="uid-undo",
            action="apply_ai_change",
            details={
                "before_event": {
                    "calendar_id": "user-id",
                    "uid": "uid-undo",
                    "summary": "Before",
                    "description": "desc",
                    "location": "",
                    "start": "2026-03-05T10:00:00+00:00",
                    "end": "2026-03-05T11:00:00+00:00",
                    "all_day": False,
                    "href": "",
                    "etag": "",
                    "source": "user",
                    "mandatory": False,
                    "locked": False,
                    "original_calendar_id": "",
                    "original_uid": "",
                }
            },
        )
        latest = self.client.app.state.context.state_store.recent_audit_events(limit=1)[0]
        fake_saved = latest["details"]["before_event"]

        class _FakeService:
            def __init__(self, _config: object) -> None:
                pass

            def upsert_event(self, _calendar_id: str, _event: object) -> object:
                return type("Evt", (), {"to_dict": lambda self: fake_saved, "calendar_id": "user-id", "uid": "uid-undo", "summary": "Before"})()

        with mock.patch("avocado.web_admin.CalDAVService", _FakeService):
            resp = self.client.post("/api/ai/changes/undo", json={"audit_id": latest["id"]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["message"], "undo applied")

    def test_revise_ai_change(self) -> None:
        self.client.app.state.context.state_store.record_audit_event(
            calendar_id="user-id",
            uid="uid-revise",
            action="apply_ai_change",
            details={"before_event": {"calendar_id": "user-id", "uid": "uid-revise"}},
        )
        latest = self.client.app.state.context.state_store.recent_audit_events(limit=1)[0]

        class _FakeEvent:
            calendar_id = "user-id"
            uid = "uid-revise"
            description = ""
            summary = "Revise Me"

            def to_dict(self) -> dict:
                return {"calendar_id": "user-id", "uid": "uid-revise"}

        class _FakeService:
            def __init__(self, _config: object) -> None:
                pass

            def get_event_by_uid(self, _calendar_id: str, _uid: str) -> object:
                return _FakeEvent()

            def upsert_event(self, _calendar_id: str, event: object) -> object:
                return event

        with mock.patch("avocado.web_admin.CalDAVService", _FakeService):
            with mock.patch.object(self.client.app.state.context.scheduler, "trigger_manual") as trigger_manual:
                resp = self.client.post(
                    "/api/ai/changes/revise",
                    json={"audit_id": latest["id"], "instruction": "Move to 3pm"},
                )
        self.assertEqual(resp.status_code, 200)
        trigger_manual.assert_called_once()

    def test_ai_request_bytes_metrics_endpoint(self) -> None:
        self.client.app.state.context.state_store.record_audit_event(
            calendar_id="system",
            uid="ai",
            action="ai_request",
            details={"request_bytes": 1234},
        )
        self.client.app.state.context.state_store.record_audit_event(
            calendar_id="system",
            uid="ai",
            action="ai_request",
            details={"request_bytes": 4321},
        )
        resp = self.client.get("/api/metrics/ai-request-bytes?days=90&limit=100")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["days"], 90)
        self.assertGreaterEqual(len(data["points"]), 2)
        self.assertIn("request_bytes", data["points"][-1])


if __name__ == "__main__":
    unittest.main()
