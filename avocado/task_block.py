from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import yaml

from avocado.models import DEFAULT_EDITABLE_FIELDS, TaskDefaultsConfig

AI_TASK_START = "[AI Task]"
AI_TASK_END = "[/AI Task]"
AI_TASK_PATTERN = re.compile(r"\[AI Task\]\s*\n(.*?)\n\[/AI Task\]", re.DOTALL)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_default_task(defaults: TaskDefaultsConfig) -> dict[str, Any]:
    return {
        "version": 1,
        "locked": bool(defaults.locked),
        "mandatory": bool(defaults.mandatory),
        "editable_fields": list(defaults.editable_fields or DEFAULT_EDITABLE_FIELDS),
        "user_intent": "",
        "constraints": {
            "earliest_start": None,
            "latest_end": None,
            "avoid_overlap_with_mandatory": True,
        },
        "priority": "medium",
        "source": "system",
        "last_editor": "system",
        "updated_at": _now_iso(),
    }


def parse_ai_task_block(description: str) -> dict[str, Any] | None:
    if not description:
        return None
    match = AI_TASK_PATTERN.search(description)
    if not match:
        return None
    payload = yaml.safe_load(match.group(1)) or {}
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
    normalized.update(parsed)
    editable_fields = normalized.get("editable_fields", defaults.editable_fields)
    if not isinstance(editable_fields, list):
        editable_fields = defaults.editable_fields
    cleaned = [str(x).strip() for x in editable_fields if str(x).strip()]
    normalized["editable_fields"] = cleaned or list(DEFAULT_EDITABLE_FIELDS)
    constraints = normalized.get("constraints", {})
    if not isinstance(constraints, dict):
        constraints = {}
    default_constraints = normalized["constraints"]
    default_constraints.update(constraints)
    normalized["constraints"] = default_constraints
    normalized["locked"] = bool(normalized.get("locked", defaults.locked))
    normalized["mandatory"] = bool(normalized.get("mandatory", defaults.mandatory))
    normalized["updated_at"] = str(normalized.get("updated_at") or _now_iso())
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

