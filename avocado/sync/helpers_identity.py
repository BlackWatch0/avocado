from __future__ import annotations

import hashlib
import re
from datetime import datetime

from avocado.core.models import EventRecord, serialize_datetime
from avocado.integrations.caldav import CalDAVService
from avocado.persistence.state_store import StateStore


def _hash_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()  # nosec B324


def _staging_uid(calendar_id: str, uid: str) -> str:
    """Legacy helper kept for compatibility with existing scripts/tests."""
    prefix = hashlib.sha1(calendar_id.encode("utf-8")).hexdigest()[:10]  # nosec B324
    return f"{prefix}:{uid}"


def _normalize_calendar_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _managed_uid_prefix_depth(uid: str) -> int:
    if not uid:
        return 0
    parts = uid.split(":")
    depth = 0
    for segment in parts[:-1]:
        if re.fullmatch(r"[0-9a-f]{10}", segment):
            depth += 1
        else:
            break
    return depth


def _collapse_nested_managed_uid(uid: str) -> str:
    depth = _managed_uid_prefix_depth(uid)
    if depth <= 1:
        return uid
    parts = uid.split(":")
    return ":".join(parts[depth - 1 :])


def _is_confirmed_avocado_calendar(calendar_id: str, known_managed_calendar_ids: set[str]) -> bool:
    return bool(calendar_id and calendar_id in known_managed_calendar_ids)


def _purge_duplicate_calendar_events(
    *,
    caldav_service: CalDAVService,
    state_store: StateStore,
    duplicate_calendars: list[tuple[str, str]],
    calendar_role: str,
    known_managed_calendar_ids: set[str],
    trigger: str,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    should_replan = False
    for duplicate_id, duplicate_name in duplicate_calendars:
        if not _is_confirmed_avocado_calendar(duplicate_id, known_managed_calendar_ids):
            state_store.record_audit_event(
                calendar_id=duplicate_id,
                uid="calendar",
                action=f"warn_unverified_duplicate_{calendar_role}_calendar",
                details={
                    "trigger": trigger,
                    "duplicate_calendar_name": duplicate_name,
                    "reason": "calendar_ownership_unverified",
                },
            )
            continue

        duplicate_events = caldav_service.fetch_events(duplicate_id, window_start, window_end)
        for duplicate_event in duplicate_events:
            if not duplicate_event.uid:
                continue
            delete_ok = caldav_service.delete_event(
                duplicate_id,
                uid=duplicate_event.uid,
                href=duplicate_event.href,
            )
            state_store.record_audit_event(
                calendar_id=duplicate_id,
                uid=duplicate_event.uid,
                action=f"purge_duplicate_{calendar_role}_calendar_event",
                details={
                    "trigger": trigger,
                    "delete_ok": delete_ok,
                    "duplicate_calendar_name": duplicate_name,
                },
            )
            should_replan = True
    return should_replan


def _event_fingerprint(event: EventRecord) -> str:
    return _hash_text(
        f"{event.summary}|{event.description}|{event.location}|"
        f"{serialize_datetime(event.start)}|{serialize_datetime(event.end)}|"
        f"{int(bool(event.locked))}|{event.x_sync_id}|{event.x_source}|{event.x_source_uid}"
    )
