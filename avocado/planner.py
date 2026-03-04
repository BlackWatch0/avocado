from __future__ import annotations

import json
from typing import Any

from avocado.core.models import DEFAULT_AI_SYSTEM_PROMPT, EventRecord

COMPACT_PAYLOAD_VERSION = "compact_v1"


def _normalize_user_intent(value: Any) -> str:
    text = str(value or "").strip()
    if text.casefold() in {"", "\"\"", "''", "null", "none", "~"}:
        return ""
    return text


def _truncate_text(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    limit = max(1, int(max_chars))
    if len(text) <= limit:
        return text
    return text[:limit]


def _build_compact_events_by_uid(
    *,
    source_events: list[dict[str, Any]],
    target_uids: list[str],
    description_max_chars: int,
) -> dict[str, dict[str, Any]]:
    compact_events: dict[str, dict[str, Any]] = {}
    target_uid_set = {str(uid or "").strip() for uid in target_uids if str(uid or "").strip()}
    for item in source_events:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("uid", "") or "").strip()
        if not uid:
            continue
        start = str(item.get("start", "") or "").strip()
        end = str(item.get("end", "") or "").strip()
        if not start or not end:
            continue

        ai_task = item.get("ai_task", {})
        if not isinstance(ai_task, dict):
            ai_task = {}

        summary = str(item.get("summary", "") or "")
        compact_item: dict[str, Any] = {
            "t": [start, end],
            "s": summary,
            "k": bool(item.get("locked", ai_task.get("locked", False))),
        }
        location = str(item.get("location", "") or "").strip()
        if location:
            compact_item["l"] = location

        user_intent = _normalize_user_intent(item.get("user_intent", ai_task.get("user_intent", "")))
        if uid in target_uid_set and user_intent:
            compact_item["i"] = user_intent

        description = str(item.get("description", "") or "")
        include_description = bool(description.strip()) and (uid in target_uid_set or not summary.strip())
        if include_description:
            compact_item["d"] = _truncate_text(description, description_max_chars)

        compact_events[uid] = compact_item
    return compact_events


def _normalize_change_item(item: dict[str, Any]) -> dict[str, Any] | None:
    uid = str(item.get("uid", "") or "").strip()
    if not uid:
        return None
    cleaned: dict[str, Any] = {"uid": uid}
    calendar_id = str(item.get("calendar_id", "") or "").strip()
    if calendar_id:
        cleaned["calendar_id"] = calendar_id
    for field in ("start", "end", "summary", "location", "description", "category", "reason"):
        if field in item and item[field] is not None:
            cleaned[field] = item[field]
    return cleaned


def _normalize_create_item(item: dict[str, Any]) -> dict[str, Any] | None:
    from_uid = str(item.get("from_uid", "") or "").strip()
    if not from_uid:
        return None
    cleaned: dict[str, Any] = {"from_uid": from_uid}
    create_key = str(item.get("create_key", "") or "").strip()
    if create_key:
        cleaned["create_key"] = create_key
    for field in ("start", "end", "summary", "location", "description", "reason", "calendar_id"):
        if field in item and item[field] is not None:
            cleaned[field] = item[field]
    return cleaned


def build_planning_payload(
    *,
    events: list[EventRecord] | None,
    window_start: str,
    window_end: str,
    timezone: str,
    events_payload: list[dict[str, Any]] | None = None,
    target_events: list[dict[str, Any]] | None = None,
    target_uids: list[str] | None = None,
    compact: bool = True,
    description_max_chars: int = 240,
) -> dict[str, Any]:
    base_payload = {
        "window": {
            "start": window_start,
            "end": window_end,
            "timezone": timezone,
        }
    }
    source_events = list(events_payload or [event.to_dict() for event in (events or [])])
    if not compact:
        payload = dict(base_payload)
        payload["events"] = source_events
        if target_events:
            payload["target_events"] = target_events
        return payload

    dedup_target_uids: list[str] = []
    seen_target_uids: set[str] = set()
    for uid in (target_uids or []):
        normalized_uid = str(uid or "").strip()
        if not normalized_uid or normalized_uid in seen_target_uids:
            continue
        dedup_target_uids.append(normalized_uid)
        seen_target_uids.add(normalized_uid)

    payload = dict(base_payload)
    payload["events_by_uid"] = _build_compact_events_by_uid(
        source_events=source_events,
        target_uids=dedup_target_uids,
        description_max_chars=description_max_chars,
    )
    payload["target_uids"] = dedup_target_uids
    return payload


def build_messages(payload: dict[str, Any], system_prompt: str | None = None) -> list[dict[str, str]]:
    prompt = (system_prompt or "").strip() or DEFAULT_AI_SYSTEM_PROMPT
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def normalize_ai_plan_result(raw_result: Any) -> dict[str, list[dict[str, Any]]]:
    result = raw_result if isinstance(raw_result, dict) else {}
    raw_changes = result.get("changes", [])
    raw_creates = result.get("creates", [])

    normalized_changes: list[dict[str, Any]] = []
    normalized_creates: list[dict[str, Any]] = []

    if isinstance(raw_changes, list):
        for item in raw_changes:
            if not isinstance(item, dict):
                continue
            cleaned = _normalize_change_item(item)
            if cleaned is not None:
                normalized_changes.append(cleaned)

    if isinstance(raw_creates, list):
        for item in raw_creates:
            if not isinstance(item, dict):
                continue
            cleaned = _normalize_create_item(item)
            if cleaned is not None:
                normalized_creates.append(cleaned)

    return {"changes": normalized_changes, "creates": normalized_creates}


def normalize_changes(raw_changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in raw_changes:
        if isinstance(item, dict):
            cleaned = _normalize_change_item(item)
            if cleaned is not None:
                normalized.append(cleaned)
    return normalized
