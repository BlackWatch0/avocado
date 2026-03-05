from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Iterable

from avocado.core.models import EventRecord, parse_iso_datetime


ALLOWED_FIELDS = {"start", "end", "summary", "location", "description"}
APPLY_FIELD_ORDER = ("start", "end", "summary", "location", "description")


def _normalize_all_day_range(start_value: datetime | None, end_value: datetime | None) -> tuple[datetime | None, datetime | None]:
    if start_value is None and end_value is None:
        return start_value, end_value
    normalized_start = start_value
    normalized_end = end_value
    if normalized_start is not None:
        normalized_start = datetime.combine(normalized_start.date(), time.min, tzinfo=timezone.utc)
    if normalized_end is not None:
        normalized_end = datetime.combine(normalized_end.date(), time.min, tzinfo=timezone.utc)
    if normalized_start is not None and normalized_end is not None and normalized_end <= normalized_start:
        normalized_end = normalized_start + timedelta(days=1)
    return normalized_start, normalized_end


@dataclass
class ReconcileOutcome:
    applied: bool
    conflicted: bool
    reason: str
    event: EventRecord
    blocked_fields: list[str]


def apply_change(
    *,
    current_event: EventRecord,
    change: dict[str, Any],
    baseline_etag: str,
    editable_fields: Iterable[str] | None = None,
) -> ReconcileOutcome:
    if current_event.locked:
        return ReconcileOutcome(
            applied=False,
            conflicted=True,
            reason="event_locked",
            event=current_event,
            blocked_fields=[],
        )

    if baseline_etag and current_event.etag and baseline_etag != current_event.etag:
        return ReconcileOutcome(
            applied=False,
            conflicted=True,
            reason="user_modified_after_planning",
            event=current_event,
            blocked_fields=[],
        )

    parsed_datetimes: dict[str, Any] = {}
    for field in ("start", "end"):
        if field not in change:
            continue
        try:
            parsed_datetimes[field] = parse_iso_datetime(change.get(field))
        except Exception:
            return ReconcileOutcome(
                applied=False,
                conflicted=True,
                reason="invalid_datetime",
                event=current_event,
                blocked_fields=[],
            )
    if current_event.all_day and ("start" in parsed_datetimes or "end" in parsed_datetimes):
        normalized_start, normalized_end = _normalize_all_day_range(
            parsed_datetimes.get("start", current_event.start),
            parsed_datetimes.get("end", current_event.end),
        )
        if "start" in parsed_datetimes:
            parsed_datetimes["start"] = normalized_start
        if "end" in parsed_datetimes:
            parsed_datetimes["end"] = normalized_end

    updated = current_event.clone()
    applied_any = False
    editable_set = {str(field).strip() for field in editable_fields or APPLY_FIELD_ORDER if str(field).strip()}
    applicable_fields = ALLOWED_FIELDS & editable_set
    blocked_fields = sorted(field for field in (ALLOWED_FIELDS - applicable_fields) if field in change)

    for field in APPLY_FIELD_ORDER:
        if field not in applicable_fields:
            continue
        if field not in change:
            continue
        if field in parsed_datetimes:
            parsed_dt = parsed_datetimes[field]
            if parsed_dt is not None and getattr(updated, field) != parsed_dt:
                setattr(updated, field, parsed_dt)
                applied_any = True
            continue
        new_value = change.get(field)
        value_text = str(new_value) if new_value is not None else ""
        if getattr(updated, field) != value_text:
            setattr(updated, field, value_text)
            applied_any = True

    return ReconcileOutcome(
        applied=applied_any,
        conflicted=False,
        reason="applied" if applied_any else "no_changes",
        event=updated,
        blocked_fields=blocked_fields,
    )
