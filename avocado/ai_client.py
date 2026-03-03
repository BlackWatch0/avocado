from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from avocado.core.models import AIConfig


JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
PAYLOAD_LOG_LOCK = threading.Lock()


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
        self.last_usage: dict[str, int] = {}

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

    def _clip_text(self, value: str) -> str:
        limit = max(1000, int(getattr(self.config, "payload_log_max_chars", 200000)))
        if len(value) <= limit:
            return value
        return value[:limit] + f"\n...[truncated {len(value) - limit} chars]"

    def _append_payload_log(
        self,
        *,
        api: str,
        method: str,
        endpoint: str,
        request_body: dict[str, Any] | None = None,
        response_status: int | None = None,
        response_body: Any | None = None,
        response_text: str | None = None,
        error: str | None = None,
    ) -> None:
        if not bool(getattr(self.config, "payload_logging_enabled", False)):
            return
        try:
            log_path = Path(
                str(
                    getattr(
                        self.config,
                        "payload_log_path",
                        "data/test_logs/ai_payload_exchange.jsonl",
                    )
                )
            )
            log_path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "api": api,
                "method": method.upper(),
                "endpoint": endpoint,
                "model": self.config.model,
                "request": request_body if request_body is not None else None,
                "response_status": response_status,
                "response_json": response_body,
                "response_text": self._clip_text(str(response_text or "")),
                "error": error or "",
            }
            line = json.dumps(payload, ensure_ascii=False, default=str)
            with PAYLOAD_LOG_LOCK:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception:
            # Payload logging is best-effort and must not break sync flow.
            return

    @staticmethod
    def _extract_usage(payload: Any) -> dict[str, int]:
        usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
        if not isinstance(usage, dict):
            return {}
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        total_tokens = int(usage.get("total_tokens", 0) or 0)
        if total_tokens <= 0:
            total_tokens = max(0, prompt_tokens) + max(0, completion_tokens)
        return {
            "prompt_tokens": max(0, prompt_tokens),
            "completion_tokens": max(0, completion_tokens),
            "total_tokens": max(0, total_tokens),
        }

    @staticmethod
    def _is_resource_unavailable_429(response: requests.Response) -> bool:
        if int(getattr(response, "status_code", 0) or 0) != 429:
            return False
        try:
            payload = response.json()
        except Exception:
            payload = {}
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        text = " ".join(
            [
                str(error.get("message", "")),
                str(error.get("type", "")),
                str(error.get("code", "")),
                str(getattr(response, "text", "")),
            ]
        ).casefold()
        return "resource unavailable" in text or "insufficient resources" in text

    def _chat_timeout_seconds(self, service_tier: str) -> int:
        base_timeout = max(1, int(getattr(self.config, "timeout_seconds", 90) or 90))
        if str(service_tier).strip().lower() == "flex":
            # Flex can be slower; use at least 15 minutes unless caller configured larger timeout.
            return max(base_timeout, 900)
        return base_timeout

    @staticmethod
    def _is_temperature_unsupported_400(response: requests.Response) -> bool:
        if int(getattr(response, "status_code", 0) or 0) != 400:
            return False
        try:
            payload = response.json()
        except Exception:
            payload = {}
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = str(error.get("message", "") or "").casefold()
        param = str(error.get("param", "") or "").casefold()
        code = str(error.get("code", "") or "").casefold()
        return (
            "temperature" in message
            and ("unsupported" in message or "only the default" in message)
            and (param in {"temperature", ""} or code == "unsupported_value")
        )

    def _post_chat(self, endpoint: str, request_payload: dict[str, Any]) -> requests.Response:
        tier = str(request_payload.get("service_tier", "") or "").strip().lower()
        return requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload,
            timeout=self._chat_timeout_seconds(tier),
        )

    def _post_chat_with_flex_policy(
        self,
        *,
        endpoint: str,
        request_payload: dict[str, Any],
    ) -> tuple[requests.Response, dict[str, Any]]:
        tier = str(request_payload.get("service_tier", "") or "").strip().lower()
        if tier != "flex":
            return self._post_chat(endpoint, request_payload), request_payload

        # Flex policy:
        # 1) retry resource-unavailable/timeout with exponential backoff
        # 2) if still failing, fallback to service_tier=auto once
        max_retries = 2
        last_timeout_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = self._post_chat(endpoint, request_payload)
            except requests.Timeout as exc:
                last_timeout_error = exc
                if attempt < max_retries:
                    time.sleep(2**attempt)
                    continue
                response = None
            if response is None:
                break
            if response.ok:
                return response, request_payload
            if self._is_resource_unavailable_429(response) and attempt < max_retries:
                time.sleep(2**attempt)
                continue
            break

        fallback_enabled = bool(getattr(self.config, "high_load_flex_fallback_to_auto", True))
        if fallback_enabled:
            fallback_payload = dict(request_payload)
            fallback_payload["service_tier"] = "auto"
            return self._post_chat(endpoint, fallback_payload), fallback_payload
        if last_timeout_error is not None:
            raise last_timeout_error
        # If retries produced a non-ok response and fallback is disabled, send one final response up.
        return self._post_chat(endpoint, request_payload), request_payload

    def generate_changes(self, *, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not self.is_configured():
            return {"changes": []}
        self.last_usage = {}
        endpoint = self._chat_endpoint()
        request_payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        service_tier = str(getattr(self.config, "_request_service_tier", "") or "").strip().lower()
        if service_tier in {"auto", "default", "flex"}:
            request_payload["service_tier"] = service_tier
        response: requests.Response | None = None
        request_payload_used = dict(request_payload)
        try:
            response, request_payload_used = self._post_chat_with_flex_policy(
                endpoint=endpoint,
                request_payload=request_payload,
            )
            if not response.ok and self._is_temperature_unsupported_400(response):
                retry_payload = dict(request_payload_used)
                retry_payload["temperature"] = 1
                response, request_payload_used = self._post_chat_with_flex_policy(
                    endpoint=endpoint,
                    request_payload=retry_payload,
                )
            response.raise_for_status()
            payload = response.json()
            self.last_usage = self._extract_usage(payload)
            self._append_payload_log(
                api="generate_changes",
                method="POST",
                endpoint=endpoint,
                request_body=request_payload_used,
                response_status=int(response.status_code),
                response_body=payload,
            )
            content = payload["choices"][0]["message"]["content"]
            json_text = _extract_json_payload(content)
            result = json.loads(json_text)
            if not isinstance(result, dict):
                raise ValueError("AI response root must be an object.")
            if "changes" not in result or not isinstance(result["changes"], list):
                result["changes"] = []
            return result
        except Exception as exc:
            self.last_usage = {}
            response_status = int(response.status_code) if response is not None else None
            response_text = ""
            if response is not None:
                try:
                    response_text = response.text
                except Exception:
                    response_text = ""
            self._append_payload_log(
                api="generate_changes",
                method="POST",
                endpoint=endpoint,
                request_body=request_payload_used,
                response_status=response_status,
                response_text=response_text,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

    def test_connectivity(self) -> tuple[bool, str]:
        if not self.is_configured():
            return False, "AI config incomplete: base_url/api_key/model required."
        self.last_usage = {}
        endpoint = self._chat_endpoint()
        request_payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": "Reply with: OK"}],
            "temperature": 0,
            "max_tokens": 8,
        }
        try:
            response = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=self.config.timeout_seconds,
            )
            response_status = int(response.status_code)
            if not response.ok:
                self._append_payload_log(
                    api="test_connectivity",
                    method="POST",
                    endpoint=endpoint,
                    request_body=request_payload,
                    response_status=response_status,
                    response_text=response.text,
                )
                return False, f"HTTP {response.status_code}: {response.text[:300]}"
            payload = response.json()
            self.last_usage = self._extract_usage(payload)
            self._append_payload_log(
                api="test_connectivity",
                method="POST",
                endpoint=endpoint,
                request_body=request_payload,
                response_status=response_status,
                response_body=payload,
            )
            content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
            content_text = str(content).strip().replace("\n", " ")
            return True, f"Connected. Model response: {content_text[:120]}"
        except Exception as exc:
            self.last_usage = {}
            self._append_payload_log(
                api="test_connectivity",
                method="POST",
                endpoint=endpoint,
                request_body=request_payload,
                error=f"{type(exc).__name__}: {exc}",
            )
            return False, f"{type(exc).__name__}: {exc}"

    def list_models(self) -> list[str]:
        if not self.is_configured():
            return []
        endpoint = self._models_endpoint()
        try:
            response = requests.get(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                },
                timeout=self.config.timeout_seconds,
            )
            response_status = int(response.status_code)
            if not response.ok:
                self._append_payload_log(
                    api="list_models",
                    method="GET",
                    endpoint=endpoint,
                    response_status=response_status,
                    response_text=response.text,
                )
                return []
            payload = response.json()
            self._append_payload_log(
                api="list_models",
                method="GET",
                endpoint=endpoint,
                response_status=response_status,
                response_body=payload,
            )
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
        except Exception as exc:
            self._append_payload_log(
                api="list_models",
                method="GET",
                endpoint=endpoint,
                error=f"{type(exc).__name__}: {exc}",
            )
            return []
