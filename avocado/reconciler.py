from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from avocado.models import EventRecord, parse_iso_datetime


ALLOWED_FIELDS = ("start", "end", "summary", "location", "description")


@dataclass
class ReconcileOutcome:
    applied: bool
    conflicted: bool
    reason: str
    event: EventRecord


def apply_change(
    *,
    current_event: EventRecord,
    change: dict[str, Any],
    baseline_etag: str,
) -> ReconcileOutcome:
    if current_event.locked or current_event.mandatory:
        return ReconcileOutcome(
            applied=False,
            conflicted=True,
            reason="event_locked_or_mandatory",
            event=current_event,
        )

    if baseline_etag and current_event.etag and baseline_etag != current_event.etag:
        return ReconcileOutcome(
            applied=False,
            conflicted=True,
            reason="user_modified_after_planning",
            event=current_event,
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
            )

    updated = current_event.clone()
    applied_any = False

    for field in ALLOWED_FIELDS:
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
    )
