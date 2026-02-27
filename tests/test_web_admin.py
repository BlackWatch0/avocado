import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

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
        ):
            resp = self.client.post("/api/ai/test")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("Connected", data["message"])

    def test_calendars_marks_managed_duplicates(self) -> None:
        update = {
            "calendar_rules": {
                "staging_calendar_id": "stage-id",
                "staging_calendar_name": "Avocado AI Staging",
                "user_calendar_id": "user-id",
                "user_calendar_name": "Avocado User Calendar",
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
                    _cal("dup-user-id", "Avocado User Calendar"),
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


if __name__ == "__main__":
    unittest.main()
