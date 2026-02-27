import os
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
