from __future__ import annotations

import json
from typing import Any

from avocado.models import DEFAULT_AI_SYSTEM_PROMPT, EventRecord


def build_planning_payload(
    *,
    events: list[EventRecord],
    immutable_calendar_ids: list[str],
    window_start: str,
    window_end: str,
    timezone: str,
) -> dict[str, Any]:
    return {
        "window": {
            "start": window_start,
            "end": window_end,
            "timezone": timezone,
        },
        "immutable_calendar_ids": immutable_calendar_ids,
        "events": [event.to_dict() for event in events],
    }


def build_messages(payload: dict[str, Any], system_prompt: str | None = None) -> list[dict[str, str]]:
    prompt = (system_prompt or "").strip() or DEFAULT_AI_SYSTEM_PROMPT
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def normalize_changes(raw_changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in raw_changes:
        if not isinstance(item, dict):
            continue
        calendar_id = str(item.get("calendar_id", "")).strip()
        uid = str(item.get("uid", "")).strip()
        if not calendar_id or not uid:
            continue
        cleaned = {
            "calendar_id": calendar_id,
            "uid": uid,
        }
        for field in ("start", "end", "summary", "location", "description", "category", "reason"):
            if field in item and item[field] is not None:
                cleaned[field] = item[field]
        normalized.append(cleaned)
    return normalized

