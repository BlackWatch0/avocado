from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from avocado.core.models import (
    AI_TASK_ALL_FIELDS,
    AI_TASK_META_FIELDS,
    AI_TASK_PUBLIC_FIELDS,
    TaskDefaultsConfig,
)

AI_TASK_START = "[AI Task]"
AI_TASK_END = "[/AI Task]"
AI_TASK_PATTERN = re.compile(r"\[AI Task\]\s*\n(.*?)\n\[/AI Task\]", re.DOTALL)
ALLOWED_TASK_KEYS = set(AI_TASK_ALL_FIELDS)
logger = logging.getLogger(__name__)


def _normalize_user_intent(value: Any) -> str:
    text = str(value or "").strip()
    if text.casefold() in {"", "\"\"", "''", "null", "none", "~"}:
        return ""
    return text


def _resolve_ai_task_template_path() -> Path:
    configured = os.getenv("AVOCADO_AI_TASK_TEMPLATE_PATH", "ai_task_template.yaml")
    return Path(configured).expanduser()


def _load_task_template() -> dict[str, Any]:
    path = _resolve_ai_task_template_path()
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.debug("Failed to read AI task template file", exc_info=True)
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def build_default_task(defaults: TaskDefaultsConfig) -> dict[str, Any]:
    template = _load_task_template()
    return {
        "locked": bool(template.get("locked", defaults.locked)),
        "user_intent": _normalize_user_intent(template.get("user_intent", "")),
    }


def parse_ai_task_block(description: str) -> dict[str, Any] | None:
    if not description:
        return None
    match = AI_TASK_PATTERN.search(description)
    if not match:
        return None
    try:
        payload = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        logger.debug("Failed to parse [AI Task] YAML block", exc_info=True)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def strip_ai_task_block(description: str) -> str:
    if not description:
        return ""
    cleaned = AI_TASK_PATTERN.sub("", description).strip()
    return cleaned


def _normalize_task(parsed: dict[str, Any], defaults: TaskDefaultsConfig) -> dict[str, Any]:
    normalized = build_default_task(defaults)
    parsed = dict(parsed or {})
    for key in ALLOWED_TASK_KEYS:
        if key in parsed:
            normalized[key] = parsed[key]
    normalized["locked"] = bool(normalized.get("locked", defaults.locked))
    normalized["user_intent"] = _normalize_user_intent(normalized.get("user_intent", ""))
    return normalized


def upsert_ai_task_block(description: str, task_payload: dict[str, Any]) -> str:
    yaml_content = yaml.safe_dump(
        task_payload,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    block = f"{AI_TASK_START}\n{yaml_content}\n{AI_TASK_END}"
    if not description:
        return block
    if AI_TASK_PATTERN.search(description):
        return AI_TASK_PATTERN.sub(block, description).strip()
    return f"{description.rstrip()}\n\n{block}".strip()


def ensure_ai_task_block(
    description: str,
    defaults: TaskDefaultsConfig,
) -> tuple[str, dict[str, Any], bool]:
    parsed = parse_ai_task_block(description)
    if parsed is None:
        task = build_default_task(defaults)
        return upsert_ai_task_block(description, task), task, True
    normalized = _normalize_task(parsed, defaults)
    updated_description = upsert_ai_task_block(description, normalized)
    changed = normalized != parsed or updated_description != description
    return updated_description, normalized, changed


def set_ai_task_category(
    description: str,
    defaults: TaskDefaultsConfig,
    category: str,
) -> tuple[str, dict[str, Any], bool]:
    _ = category
    return ensure_ai_task_block(description, defaults)


def set_ai_task_user_intent(
    description: str,
    defaults: TaskDefaultsConfig,
    user_intent: str,
) -> tuple[str, dict[str, Any], bool]:
    updated_description, task_payload, changed = ensure_ai_task_block(description, defaults)
    normalized_intent = _normalize_user_intent(user_intent)
    if _normalize_user_intent(task_payload.get("user_intent", "")) == normalized_intent:
        return updated_description, task_payload, changed
    task_payload["user_intent"] = normalized_intent
    final_description = upsert_ai_task_block(updated_description, task_payload)
    return final_description, task_payload, True


def ai_task_payload_from_description(
    description: str,
    defaults: TaskDefaultsConfig,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    normalized_description, task_payload, _ = ensure_ai_task_block(description or "", defaults)
    visible_description = strip_ai_task_block(normalized_description)
    ai_task = {key: task_payload.get(key) for key in AI_TASK_PUBLIC_FIELDS}
    x_meta = {f"x-{key}": task_payload.get(key) for key in AI_TASK_META_FIELDS}
    return visible_description, ai_task, x_meta
