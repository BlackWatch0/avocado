from __future__ import annotations

import json
import re
from typing import Any

import requests

from avocado.models import AIConfig


JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def _extract_json_payload(content: str) -> str:
    text = content.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    block = JSON_BLOCK_PATTERN.search(text)
    if block:
        return block.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    raise ValueError("AI response does not contain valid JSON.")


class OpenAICompatibleClient:
    def __init__(self, config: AIConfig) -> None:
        self.config = config

    def is_configured(self) -> bool:
        return bool(self.config.base_url and self.config.api_key and self.config.model)

    def _chat_endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _models_endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return f"{base[:-len('/chat/completions')]}/models"
        return f"{base}/models"

    def generate_changes(self, *, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not self.is_configured():
            return {"changes": []}
        response = requests.post(
            self._chat_endpoint(),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "messages": messages,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        json_text = _extract_json_payload(content)
        result = json.loads(json_text)
        if not isinstance(result, dict):
            raise ValueError("AI response root must be an object.")
        if "changes" not in result or not isinstance(result["changes"], list):
            result["changes"] = []
        return result

    def test_connectivity(self) -> tuple[bool, str]:
        if not self.is_configured():
            return False, "AI config incomplete: base_url/api_key/model required."
        try:
            response = requests.post(
                self._chat_endpoint(),
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.config.model,
                    "messages": [{"role": "user", "content": "Reply with: OK"}],
                    "temperature": 0,
                    "max_tokens": 8,
                },
                timeout=self.config.timeout_seconds,
            )
            if not response.ok:
                return False, f"HTTP {response.status_code}: {response.text[:300]}"
            payload = response.json()
            content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
            content_text = str(content).strip().replace("\n", " ")
            return True, f"Connected. Model response: {content_text[:120]}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def list_models(self) -> list[str]:
        if not self.is_configured():
            return []
        try:
            response = requests.get(
                self._models_endpoint(),
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                },
                timeout=self.config.timeout_seconds,
            )
            if not response.ok:
                return []
            payload = response.json()
            raw_items = payload.get("data", []) if isinstance(payload, dict) else []
            model_ids: list[str] = []
            for item in raw_items:
                model_id = str((item or {}).get("id", "")).strip()
                if model_id:
                    model_ids.append(model_id)
            # keep stable order, remove duplicates
            seen: set[str] = set()
            deduped: list[str] = []
            for model_id in model_ids:
                if model_id in seen:
                    continue
                seen.add(model_id)
                deduped.append(model_id)
            return deduped
        except Exception:
            return []

