from __future__ import annotations

import re
from typing import Any

from avocado.core.models import EventRecord, parse_iso_datetime


def masked_meta(config_dict: dict[str, Any]) -> dict[str, Any]:
    has_caldav_password = bool(config_dict.get("caldav", {}).get("password", "").strip())
    has_ai_api_key = bool(config_dict.get("ai", {}).get("api_key", "").strip())
    return {
        "caldav": {"password": {"is_masked": has_caldav_password}},
        "ai": {"api_key": {"is_masked": has_ai_api_key}},
    }


def sanitize_config_payload(payload: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    current_caldav_password = str(current.get("caldav", {}).get("password", ""))
    current_ai_api_key = str(current.get("ai", {}).get("api_key", ""))

    caldav = sanitized.get("caldav")
    if isinstance(caldav, dict):
        password = caldav.get("password")
        if password is not None:
            password_text = str(password).strip()
            if password_text in {"", "***"}:
                if current_caldav_password:
                    caldav.pop("password", None)
                else:
                    caldav["password"] = ""
        if not caldav:
            sanitized.pop("caldav", None)

    ai = sanitized.get("ai")
    if isinstance(ai, dict):
        api_key = ai.get("api_key")
        if api_key is not None:
            api_key_text = str(api_key).strip()
            if api_key_text in {"", "***"}:
                if current_ai_api_key:
                    ai.pop("api_key", None)
                else:
                    ai["api_key"] = ""
        if not ai:
            sanitized.pop("ai", None)

    return sanitized


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def event_from_dict(payload: dict[str, Any]) -> EventRecord:
    return EventRecord(
        calendar_id=str(payload.get("calendar_id", "")).strip(),
        uid=str(payload.get("uid", "")).strip(),
        summary=str(payload.get("summary", "")).strip(),
        description=str(payload.get("description", "") or ""),
        location=str(payload.get("location", "") or ""),
        start=parse_iso_datetime(payload.get("start")),
        end=parse_iso_datetime(payload.get("end")),
        all_day=bool(payload.get("all_day", False)),
        href=str(payload.get("href", "") or ""),
        etag=str(payload.get("etag", "") or ""),
        source=str(payload.get("source", "user") or "user"),
        x_sync_id=str(payload.get("x_sync_id", "") or ""),
        x_source=str(payload.get("x_source", "") or ""),
        x_source_uid=str(payload.get("x_source_uid", "") or ""),
        locked=bool(payload.get("locked", False)),
        original_calendar_id=str(payload.get("original_calendar_id", "") or ""),
        original_uid=str(payload.get("original_uid", "") or ""),
    )
