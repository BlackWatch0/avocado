import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from avocado.ai_client import OpenAICompatibleClient
from avocado.core.models import AIConfig


class AIClientPayloadLoggingTests(unittest.TestCase):
    def _make_client(self, log_path: Path) -> OpenAICompatibleClient:
        cfg = AIConfig(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="gpt-4o-mini",
            payload_logging_enabled=True,
            payload_log_path=str(log_path),
            payload_log_max_chars=10000,
        )
        return OpenAICompatibleClient(cfg)

    def test_generate_changes_writes_request_and_response_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "ai_payload_exchange.jsonl"
            client = self._make_client(log_path)
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {
                "choices": [{"message": {"content": '{"changes": []}'}}],
            }
            with mock.patch("avocado.ai_client.requests.post", return_value=mock_response):
                result = client.generate_changes(messages=[{"role": "user", "content": "test"}])
            self.assertEqual(result, {"changes": []})
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["api"], "generate_changes")
            self.assertEqual(payload["method"], "POST")
            self.assertEqual(payload["response_status"], 200)
            self.assertEqual(payload["request"]["model"], "gpt-4o-mini")
            self.assertTrue(isinstance(payload["response_json"], dict))
            self.assertEqual(payload["error"], "")

    def test_generate_changes_writes_error_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "ai_payload_exchange.jsonl"
            client = self._make_client(log_path)
            mock_response = mock.Mock()
            mock_response.status_code = 500
            mock_response.text = "server error"
            mock_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
            with mock.patch("avocado.ai_client.requests.post", return_value=mock_response):
                with self.assertRaises(requests.HTTPError):
                    client.generate_changes(messages=[{"role": "user", "content": "test"}])
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["api"], "generate_changes")
            self.assertEqual(payload["response_status"], 500)
            self.assertIn("HTTPError", payload["error"])
            self.assertTrue(payload["response_text"])

    def test_generate_changes_flex_429_retries_then_fallback_auto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "ai_payload_exchange.jsonl"
            client = self._make_client(log_path)
            client.config._request_service_tier = "flex"

            mock_429 = mock.Mock()
            mock_429.status_code = 429
            mock_429.ok = False
            mock_429.text = "resource unavailable"
            mock_429.json.return_value = {"error": {"message": "Resource unavailable"}}
            mock_429.raise_for_status.side_effect = requests.HTTPError("429 Resource Unavailable")

            mock_ok = mock.Mock()
            mock_ok.status_code = 200
            mock_ok.ok = True
            mock_ok.raise_for_status.return_value = None
            mock_ok.json.return_value = {
                "choices": [{"message": {"content": '{"changes": []}'}}],
            }

            with (
                mock.patch("avocado.ai_client.requests.post", side_effect=[mock_429, mock_429, mock_429, mock_ok]) as post_mock,
                mock.patch("avocado.ai_client.time.sleep", return_value=None),
            ):
                result = client.generate_changes(messages=[{"role": "user", "content": "test"}])

            self.assertEqual(result, {"changes": []})
            self.assertEqual(post_mock.call_count, 4)
            last_call_json = post_mock.call_args.kwargs.get("json", {})
            self.assertEqual(last_call_json.get("service_tier"), "auto")
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["response_status"], 200)
            self.assertEqual(payload["request"].get("service_tier"), "auto")

    def test_generate_changes_flex_timeout_fallback_auto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "ai_payload_exchange.jsonl"
            client = self._make_client(log_path)
            client.config._request_service_tier = "flex"

            mock_ok = mock.Mock()
            mock_ok.status_code = 200
            mock_ok.ok = True
            mock_ok.raise_for_status.return_value = None
            mock_ok.json.return_value = {
                "choices": [{"message": {"content": '{"changes": []}'}}],
            }

            with (
                mock.patch(
                    "avocado.ai_client.requests.post",
                    side_effect=[requests.Timeout("timeout"), requests.Timeout("timeout"), requests.Timeout("timeout"), mock_ok],
                ) as post_mock,
                mock.patch("avocado.ai_client.time.sleep", return_value=None),
            ):
                result = client.generate_changes(messages=[{"role": "user", "content": "test"}])

            self.assertEqual(result, {"changes": []})
            self.assertEqual(post_mock.call_count, 4)
            last_call_json = post_mock.call_args.kwargs.get("json", {})
            self.assertEqual(last_call_json.get("service_tier"), "auto")

    def test_generate_changes_gpt5_omits_temperature_and_sends_reasoning_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "ai_payload_exchange.jsonl"
            client = self._make_client(log_path)
            client.config.model = "gpt-5"
            client.config._request_reasoning_effort = "low"

            mock_ok = mock.Mock()
            mock_ok.status_code = 200
            mock_ok.ok = True
            mock_ok.raise_for_status.return_value = None
            mock_ok.json.return_value = {
                "choices": [{"message": {"content": '{"changes": []}'}}],
            }

            with mock.patch("avocado.ai_client.requests.post", return_value=mock_ok) as post_mock:
                result = client.generate_changes(messages=[{"role": "user", "content": "test"}])

            self.assertEqual(result, {"changes": []})
            self.assertEqual(post_mock.call_count, 1)
            sent_json = post_mock.call_args.kwargs.get("json", {})
            self.assertNotIn("temperature", sent_json)
            self.assertEqual(sent_json.get("reasoning_effort"), "low")
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["response_status"], 200)
            self.assertEqual(payload["request"].get("reasoning_effort"), "low")

    def test_generate_changes_retries_without_reasoning_effort_on_unsupported_400(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "ai_payload_exchange.jsonl"
            client = self._make_client(log_path)
            client.config.model = "gpt-5"
            client.config._request_reasoning_effort = "low"

            mock_400 = mock.Mock()
            mock_400.status_code = 400
            mock_400.ok = False
            mock_400.text = "{\"error\":{\"message\":\"Unsupported value: 'reasoning_effort'\"}}"
            mock_400.json.return_value = {
                "error": {
                    "message": "Unsupported value: 'reasoning_effort'",
                    "type": "invalid_request_error",
                    "param": "reasoning_effort",
                    "code": "unsupported_value",
                }
            }

            mock_ok = mock.Mock()
            mock_ok.status_code = 200
            mock_ok.ok = True
            mock_ok.raise_for_status.return_value = None
            mock_ok.json.return_value = {
                "choices": [{"message": {"content": '{"changes": []}'}}],
            }

            with mock.patch("avocado.ai_client.requests.post", side_effect=[mock_400, mock_ok]) as post_mock:
                result = client.generate_changes(messages=[{"role": "user", "content": "test"}])

            self.assertEqual(result, {"changes": []})
            self.assertEqual(post_mock.call_count, 2)
            first_json = post_mock.call_args_list[0].kwargs.get("json", {})
            second_json = post_mock.call_args_list[1].kwargs.get("json", {})
            self.assertEqual(first_json.get("reasoning_effort"), "low")
            self.assertNotIn("reasoning_effort", second_json)


if __name__ == "__main__":
    unittest.main()
