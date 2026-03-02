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


if __name__ == "__main__":
    unittest.main()
