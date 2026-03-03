from __future__ import annotations

import re
from typing import Any

from avocado.core.models import EventRecord
from avocado.task_block import _coerce_locked_value, parse_ai_task_block


def _normalize_intent_value(value: Any) -> str:
    text = str(value or "").strip()
    if text.casefold() in {"", "\"\"", "''", "null", "none", "~"}:
        return ""
    return text


def _event_has_user_intent(event: EventRecord) -> bool:
    parsed = parse_ai_task_block(event.description or "")
    if isinstance(parsed, dict):
        return bool(_normalize_intent_value(parsed.get("user_intent", "")))
    description = event.description or ""
    block_match = re.search(r"\[AI Task\]\s*\n(.*?)\n\[/AI Task\]", description, re.DOTALL)
    if not block_match:
        return False
    raw_block = block_match.group(1)
    intent_match = re.search(r"^\s*user_intent\s*:\s*(.+)\s*$", raw_block, re.MULTILINE)
    if not intent_match:
        return False
    return bool(_normalize_intent_value(intent_match.group(1)))


def _event_locked_for_ai(event: EventRecord) -> bool:
    parsed = parse_ai_task_block(event.description or "")
    if isinstance(parsed, dict) and "locked" in parsed:
        return _coerce_locked_value(parsed.get("locked"), bool(event.locked))
    return bool(event.locked)


def _extract_user_intent(event: EventRecord) -> str:
    parsed = parse_ai_task_block(event.description or "")
    if isinstance(parsed, dict):
        return _normalize_intent_value(parsed.get("user_intent", ""))
    description = event.description or ""
    block_match = re.search(r"\[AI Task\]\s*\n(.*?)\n\[/AI Task\]", description, re.DOTALL)
    if not block_match:
        return ""
    raw_block = block_match.group(1)
    intent_match = re.search(r"^\s*user_intent\s*:\s*(.+)\s*$", raw_block, re.MULTILINE)
    if not intent_match:
        return ""
    return _normalize_intent_value(intent_match.group(1))


def _extract_editable_fields(event: EventRecord, fallback_fields: list[str]) -> list[str]:
    parsed = parse_ai_task_block(event.description or "")
    if isinstance(parsed, dict):
        editable_fields = parsed.get("editable_fields")
        if isinstance(editable_fields, list):
            cleaned = [str(field).strip() for field in editable_fields if str(field).strip()]
            if cleaned:
                return cleaned
    return [str(field).strip() for field in fallback_fields if str(field).strip()]


def _intent_requests_time_change(intent: str) -> bool:
    text = str(intent or "").strip()
    if not text:
        return False
    lowered = text.casefold()
    keyword_hits = [
        "before",
        "after",
        "earlier",
        "later",
        "move",
        "shift",
        "reschedule",
        "around",
        " at ",
        "time",
        "提前",
        "延后",
        "推迟",
        "改到",
        "时间",
    ]
    if any(token in lowered for token in keyword_hits):
        return True
    if re.search(r"\b\d{1,2}:\d{2}\b", text):
        return True
    if re.search(r"\b\d{1,2}\s*(am|pm)\b", lowered):
        return True
    return False


def _intent_prefers_description_only(intent: str) -> bool:
    text = str(intent or "").strip()
    if not text:
        return False
    lowered = text.casefold()
    description_keywords = ["description", "note", "notes", "summary", "简介", "描述", "备注", "说明"]
    return any(token in lowered for token in description_keywords) and not _intent_requests_time_change(text)
