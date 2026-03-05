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
AI_TASK_PATTERN = re.compile(r"\[AI Task\]\s*(.*?)\s*\[/AI Task\]", re.DOTALL)
ALLOWED_TASK_KEYS = set(AI_TASK_ALL_FIELDS)
logger = logging.getLogger(__name__)
LOCK_MARKER_PATTERN = re.compile(r"(?:^|\s)\.lock(?:\s|$)", re.IGNORECASE)
MESSAGE_MARKER_LINE_PATTERN = re.compile(r"^\s*\.m\s+(.+?)\s*$", re.IGNORECASE)
ORPHAN_AI_TASK_MARKER_LINE_PATTERN = re.compile(r"^\s*\[/?AI Task\]\s*$", re.IGNORECASE)


def _normalize_user_intent(value: Any) -> str:
    text = str(value or "").strip()
    if text.casefold() in {"", "\"\"", "''", "null", "none", "~"}:
        return ""
    return text


def _coerce_locked_value(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value or "").strip().casefold()
    if not text:
        return bool(fallback)
    true_values = {"1", "true", "t", "yes", "y", "on", "lock", "locked"}
    false_values = {"0", "false", "f", "fause", "no", "n", "off", "unlock", "unlocked"}
    if text in true_values:
        return True
    if text in false_values:
        return False
    return bool(fallback)


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
        "locked": _coerce_locked_value(template.get("locked"), defaults.locked),
        "user_intent": _normalize_user_intent(template.get("user_intent", "")),
    }


def _has_lock_marker(description: str) -> bool:
    text = strip_ai_task_block(description or "")
    if not text:
        return False
    return bool(LOCK_MARKER_PATTERN.search(text))


def _strip_lock_marker_from_visible_description(description: str) -> str:
    text = strip_ai_task_block(description or "")
    if not text:
        return ""
    cleaned = re.sub(r"(?i)(?<!\S)\.lock(?!\S)", "", text)
    lines = []
    for line in cleaned.splitlines():
        line = re.sub(r"[ \t]{2,}", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def _extract_message_intent(description: str) -> str:
    text = strip_ai_task_block(description or "")
    if not text:
        return ""
    for raw_line in text.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        match = MESSAGE_MARKER_LINE_PATTERN.match(line)
        if not match:
            continue
        return _normalize_user_intent(match.group(1))
    return ""


def _strip_message_marker_from_visible_description(description: str) -> str:
    text = strip_ai_task_block(description or "")
    if not text:
        return ""
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        if MESSAGE_MARKER_LINE_PATTERN.match(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _strip_orphan_ai_task_markers(description: str) -> str:
    text = str(description or "")
    if not text:
        return ""
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = str(raw_line or "")
        if ORPHAN_AI_TASK_MARKER_LINE_PATTERN.match(line.strip()):
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned


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
    cleaned = AI_TASK_PATTERN.sub("", description)
    cleaned = _strip_orphan_ai_task_markers(cleaned)
    return cleaned.strip()


def _normalize_task(parsed: dict[str, Any], defaults: TaskDefaultsConfig) -> dict[str, Any]:
    normalized = build_default_task(defaults)
    parsed = dict(parsed or {})
    for key in ALLOWED_TASK_KEYS:
        if key in parsed:
            normalized[key] = parsed[key]
    normalized["locked"] = _coerce_locked_value(normalized.get("locked", defaults.locked), defaults.locked)
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
    sanitized_description = _strip_orphan_ai_task_markers(description).rstrip()
    if not sanitized_description:
        return block
    return f"{sanitized_description}\n\n{block}".strip()


def ensure_ai_task_block(
    description: str,
    defaults: TaskDefaultsConfig,
) -> tuple[str, dict[str, Any], bool]:
    parsed = parse_ai_task_block(description)
    if parsed is None:
        task = build_default_task(defaults)
        base_description = description
        message_intent = _extract_message_intent(description)
        if message_intent:
            task["user_intent"] = message_intent
            base_description = _strip_message_marker_from_visible_description(base_description)
        if _has_lock_marker(description):
            task["locked"] = True
            base_description = _strip_lock_marker_from_visible_description(base_description)
        return upsert_ai_task_block(base_description, task), task, True
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


def set_ai_task_locked(
    description: str,
    defaults: TaskDefaultsConfig,
    locked: bool,
) -> tuple[str, dict[str, Any], bool]:
    updated_description, task_payload, changed = ensure_ai_task_block(description, defaults)
    normalized_locked = bool(locked)
    if _coerce_locked_value(task_payload.get("locked", False), defaults.locked) == normalized_locked:
        return updated_description, task_payload, changed
    task_payload["locked"] = normalized_locked
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
