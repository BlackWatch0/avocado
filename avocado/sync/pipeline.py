from __future__ import annotations

import json
import hashlib
import re
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any

from avocado.ai_client import OpenAICompatibleClient
from avocado.core.models import EventRecord, SyncResult, parse_iso_datetime, serialize_datetime
from avocado.integrations.caldav import CalDAVService
from avocado.planner import COMPACT_PAYLOAD_VERSION, build_messages, build_planning_payload, normalize_ai_plan_result
from avocado.reconciler import apply_change
from avocado.sync.helpers_identity import _event_fingerprint, _hash_text
from avocado.sync.helpers_intent import (
    _event_has_user_intent,
    _event_locked_for_ai,
    _extract_editable_fields,
    _extract_user_intent,
)
from avocado.task_block import (
    ai_task_payload_from_description,
    ensure_ai_task_block,
    set_ai_task_locked,
    set_ai_task_user_intent,
)
from avocado.timezone_utils import resolve_effective_timezone

LOCK_NAME_PATTERN = re.compile(r"\[\s*l\s*\]", re.IGNORECASE)


def _event_overlap(a: EventRecord, b: EventRecord) -> bool:
    if a.start is None or a.end is None or b.start is None or b.end is None:
        return False
    if a.end <= a.start or b.end <= b.start:
        return False
    return a.start < b.end and b.start < a.end


def _busy_seconds_in_window(events: list[EventRecord], window_start: datetime, window_end: datetime) -> float:
    spans: list[tuple[datetime, datetime]] = []
    for event in events:
        if event.start is None or event.end is None:
            continue
        start = max(event.start, window_start)
        end = min(event.end, window_end)
        if end <= start:
            continue
        spans.append((start, end))
    if not spans:
        return 0.0
    spans.sort(key=lambda item: item[0])
    merged: list[tuple[datetime, datetime]] = []
    cur_start, cur_end = spans[0]
    for start, end in spans[1:]:
        if start <= cur_end:
            if end > cur_end:
                cur_end = end
            continue
        merged.append((cur_start, cur_end))
        cur_start, cur_end = start, end
    merged.append((cur_start, cur_end))
    return float(sum((end - start).total_seconds() for start, end in merged))


def _compute_high_load_auto_metrics(
    *,
    planning_events: list[EventRecord],
    window_start: datetime,
    window_end: datetime,
    event_baseline: int,
    score_threshold: float,
) -> dict[str, Any]:
    event_count = len(planning_events)
    window_seconds = max((window_end - window_start).total_seconds(), 1.0)
    busy_seconds = _busy_seconds_in_window(planning_events, window_start, window_end)
    density_ratio = min(1.0, max(0.0, busy_seconds / window_seconds))
    count_ratio = min(1.0, max(0.0, float(event_count) / float(max(1, event_baseline))))

    conflict_pairs = 0
    conflicting_indexes: set[int] = set()
    for idx in range(event_count):
        for jdx in range(idx + 1, event_count):
            if _event_overlap(planning_events[idx], planning_events[jdx]):
                conflict_pairs += 1
                conflicting_indexes.add(idx)
                conflicting_indexes.add(jdx)
    conflict_ratio = min(1.0, float(len(conflicting_indexes)) / float(max(1, event_count)))

    score = (0.45 * density_ratio) + (0.35 * count_ratio) + (0.20 * conflict_ratio)
    active = bool(score >= max(0.0, score_threshold))
    return {
        "active": active,
        "score": round(score, 6),
        "density_ratio": round(density_ratio, 6),
        "count_ratio": round(count_ratio, 6),
        "conflict_ratio": round(conflict_ratio, 6),
        "event_count": int(event_count),
        "event_baseline": int(max(1, event_baseline)),
        "conflict_pairs": int(conflict_pairs),
        "score_threshold": float(max(0.0, score_threshold)),
    }


def _event_sort_key_for_context(item: dict[str, Any]) -> tuple[datetime, datetime, str]:
    start_text = str(item.get("start", "") or "").strip()
    end_text = str(item.get("end", "") or "").strip()
    try:
        start_dt = parse_iso_datetime(start_text) or datetime.max.replace(tzinfo=timezone.utc)
    except Exception:
        start_dt = datetime.max.replace(tzinfo=timezone.utc)
    try:
        end_dt = parse_iso_datetime(end_text) or datetime.max.replace(tzinfo=timezone.utc)
    except Exception:
        end_dt = datetime.max.replace(tzinfo=timezone.utc)
    uid = str(item.get("uid", "") or "").strip()
    return start_dt, end_dt, uid


def _ordered_event_uids(payload_events: list[dict[str, Any]]) -> list[str]:
    sorted_events = sorted(payload_events, key=_event_sort_key_for_context)
    ordered: list[str] = []
    seen: set[str] = set()
    for item in sorted_events:
        uid = str(item.get("uid", "") or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        ordered.append(uid)
    return ordered


def _cap_full_detail_uids(
    *,
    payload_events: list[dict[str, Any]],
    target_uids: list[str],
    preferred_uids: set[str],
    max_full_detail_events: int,
) -> set[str]:
    ordered_targets: list[str] = []
    seen_targets: set[str] = set()
    for uid in target_uids:
        uid_text = str(uid or "").strip()
        if not uid_text or uid_text in seen_targets:
            continue
        seen_targets.add(uid_text)
        ordered_targets.append(uid_text)
    event_uid_order = _ordered_event_uids(payload_events)
    max_count = max(1, int(max_full_detail_events))
    max_count = max(max_count, len(ordered_targets))
    ordered_selected: list[str] = []
    seen_selected: set[str] = set()

    def _append(uid: str) -> None:
        if len(ordered_selected) >= max_count:
            return
        if not uid or uid in seen_selected:
            return
        if uid not in preferred_uids and uid not in seen_targets:
            return
        seen_selected.add(uid)
        ordered_selected.append(uid)

    for uid in ordered_targets:
        _append(uid)
    for uid in event_uid_order:
        _append(uid)
    return set(ordered_selected)


def _build_full_detail_uid_set_for_targets(
    payload_events: list[dict[str, Any]],
    target_uids: list[str],
    neighbor_count: int = 1,
    max_full_detail_events: int = 10,
) -> set[str]:
    sorted_events = sorted(payload_events, key=_event_sort_key_for_context)
    uid_to_index: dict[str, int] = {}
    for index, item in enumerate(sorted_events):
        uid = str(item.get("uid", "") or "").strip()
        if uid and uid not in uid_to_index:
            uid_to_index[uid] = index
    ordered_target_uids: list[str] = []
    seen_targets: set[str] = set()
    for uid in target_uids:
        uid_text = str(uid or "").strip()
        if not uid_text or uid_text in seen_targets:
            continue
        seen_targets.add(uid_text)
        ordered_target_uids.append(uid_text)
    full_uids: set[str] = set(ordered_target_uids)
    max_count = max(1, int(max_full_detail_events))
    max_count = max(max_count, len(ordered_target_uids))
    radius = max(0, int(neighbor_count))
    if radius > 0:
        for offset in range(1, radius + 1):
            for target_uid in ordered_target_uids:
                if len(full_uids) >= max_count:
                    break
                index = uid_to_index.get(target_uid)
                if index is None:
                    continue
                neighbor_indexes = [index - offset, index + offset]
                for neighbor_index in neighbor_indexes:
                    if len(full_uids) >= max_count:
                        break
                    if neighbor_index < 0 or neighbor_index >= len(sorted_events):
                        continue
                    neighbor_uid = str(sorted_events[neighbor_index].get("uid", "") or "").strip()
                    if neighbor_uid:
                        full_uids.add(neighbor_uid)
            if len(full_uids) >= max_count:
                break
    return _cap_full_detail_uids(
        payload_events=payload_events,
        target_uids=ordered_target_uids,
        preferred_uids=full_uids,
        max_full_detail_events=max_count,
    )


def _context_request_to_range(item: dict[str, Any]) -> tuple[datetime, datetime] | None:
    if not isinstance(item, dict):
        return None
    start_text = str(item.get("start", "") or "").strip()
    end_text = str(item.get("end", "") or "").strip()
    date_text = str(item.get("date", "") or "").strip()
    if date_text:
        try:
            day = date.fromisoformat(date_text)
            start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            end = start + timedelta(days=1)
            return start, end
        except Exception:
            return None
    if not start_text or not end_text:
        return None
    try:
        start = parse_iso_datetime(start_text)
        end = parse_iso_datetime(end_text)
    except Exception:
        return None
    if start is None or end is None or end <= start:
        return None
    return start, end


def _expand_full_detail_uids_by_context_requests(
    payload_events: list[dict[str, Any]],
    base_full_uids: set[str],
    context_requests: list[dict[str, Any]],
    target_uids: list[str],
    max_full_detail_events: int,
) -> set[str]:
    full_uids = set(base_full_uids)
    ranges = [_context_request_to_range(item) for item in context_requests]
    valid_ranges = [item for item in ranges if item is not None]
    if not valid_ranges:
        return _cap_full_detail_uids(
            payload_events=payload_events,
            target_uids=target_uids,
            preferred_uids=full_uids,
            max_full_detail_events=max_full_detail_events,
        )
    for item in payload_events:
        uid = str(item.get("uid", "") or "").strip()
        if not uid:
            continue
        start_text = str(item.get("start", "") or "").strip()
        end_text = str(item.get("end", "") or "").strip()
        try:
            event_start = parse_iso_datetime(start_text)
            event_end = parse_iso_datetime(end_text)
        except Exception:
            continue
        if event_start is None or event_end is None or event_end <= event_start:
            continue
        for range_start, range_end in valid_ranges:
            if event_start < range_end and event_end > range_start:
                full_uids.add(uid)
                break
    return _cap_full_detail_uids(
        payload_events=payload_events,
        target_uids=target_uids,
        preferred_uids=full_uids,
        max_full_detail_events=max_full_detail_events,
    )


def _extract_iso_day(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = parse_iso_datetime(text)
    except Exception:
        return None
    if parsed is None:
        return None
    return parsed.date()


def _event_is_frozen(event: EventRecord, *, freeze_hours: int, freeze_cutoff: datetime) -> bool:
    if not bool(freeze_hours):
        return False
    if event.start is None:
        return False
    return event.start.astimezone(timezone.utc) <= freeze_cutoff


def _event_is_expired(event: EventRecord, *, now_utc: datetime) -> bool:
    if event.end is not None:
        return event.end.astimezone(timezone.utc) <= now_utc
    if event.start is not None:
        return event.start.astimezone(timezone.utc) <= now_utc
    return False


class PipelineMixin:
    def run_once(
        self,
        trigger: str = "manual",
        window_start_override: datetime | None = None,
        window_end_override: datetime | None = None,
    ) -> SyncResult:
        started_at = datetime.now(timezone.utc)
        changes_applied = 0
        conflicts = 0
        run_id = self.state_store.start_sync_run(trigger=trigger, message="running")

        def _audit(*, calendar_id: str, uid: str, action: str, details: dict[str, Any]) -> None:
            payload = dict(details or {})
            payload.setdefault("trigger", trigger)
            payload.setdefault("run_id", run_id)
            self.state_store.record_audit_event(
                calendar_id=calendar_id,
                uid=uid,
                action=action,
                details=payload,
                run_id=run_id,
            )

        try:
            config = self.config_manager.load()
            self.config_manager.save(config)
            self.state_store.set_meta("sync_engine_schema_version", self.ENGINE_SCHEMA_VERSION)

            if not config.caldav.base_url or not config.caldav.username:
                duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
                message = "CalDAV config missing base_url/username. Sync skipped."
                self.state_store.finish_sync_run(
                    run_id=run_id,
                    status="skipped",
                    message=message,
                    duration_ms=duration_ms,
                    changes_applied=0,
                    conflicts=0,
                )
                return SyncResult(
                    status="skipped",
                    message=message,
                    duration_ms=duration_ms,
                    changes_applied=0,
                    conflicts=0,
                    trigger=trigger,
                )

            caldav_service = CalDAVService(config.caldav)
            calendars = caldav_service.list_calendars()
            stack_info = caldav_service.ensure_managed_calendar(
                config.calendar_rules.stack_calendar_id,
                config.calendar_rules.stack_calendar_name,
            )
            user_info = caldav_service.ensure_managed_calendar(
                config.calendar_rules.user_calendar_id,
                config.calendar_rules.user_calendar_name,
            )
            new_info = caldav_service.ensure_managed_calendar(
                config.calendar_rules.new_calendar_id,
                config.calendar_rules.new_calendar_name,
            )

            calendar_rule_updates: dict[str, Any] = {}
            if config.calendar_rules.stack_calendar_id != stack_info.calendar_id:
                calendar_rule_updates["stack_calendar_id"] = stack_info.calendar_id
            if config.calendar_rules.user_calendar_id != user_info.calendar_id:
                calendar_rule_updates["user_calendar_id"] = user_info.calendar_id
            if config.calendar_rules.new_calendar_id != new_info.calendar_id:
                calendar_rule_updates["new_calendar_id"] = new_info.calendar_id
            if calendar_rule_updates:
                self.config_manager.update({"calendar_rules": calendar_rule_updates})
                config = self.config_manager.load()

            managed_calendar_ids = {stack_info.calendar_id, user_info.calendar_id, new_info.calendar_id}
            external_calendars = sorted(
                [calendar for calendar in calendars if calendar.calendar_id not in managed_calendar_ids],
                key=lambda item: item.calendar_id,
            )

            if self.state_store.get_meta("engine_rollout_mode") != self.ROLLOUT_MODE:
                self._clear_stack_for_migration(
                    caldav_service=caldav_service,
                    stack_calendar_id=stack_info.calendar_id,
                    trigger=trigger,
                    run_id=run_id,
                )
                self.state_store.set_meta("engine_rollout_mode", self.ROLLOUT_MODE)

            effective_timezone = resolve_effective_timezone(
                configured_timezone=config.sync.timezone,
                timezone_source=getattr(config.sync, "timezone_source", "host"),
            )
            window_start, window_end = self._window_bounds(
                window_days=config.sync.window_days,
                timezone_name=effective_timezone,
                start_override=window_start_override,
                end_override=window_end_override,
            )
            query_window_end = self._query_window_end(window_start, window_end)
            planning_now = datetime.now(timezone.utc)
            _audit(
                calendar_id="system",
                uid="sync",
                action="window_selected",
                details={
                    "window_start": serialize_datetime(window_start),
                    "window_end": serialize_datetime(window_end),
                    "timezone": effective_timezone,
                    "manual_window": window_start_override is not None,
                },
            )

            sources: list[tuple[str, str]] = [
                ("user", user_info.calendar_id),
                ("new", new_info.calendar_id),
            ] + [("ext", item.calendar_id) for item in external_calendars]

            delta_by_source: dict[str, dict[str, Any]] = {}
            for source, calendar_id in sources:
                source_key = self._source_key(source, calendar_id)
                token = self.state_store.get_sync_token(source_key=source_key)
                delta = caldav_service.fetch_changes_by_token(calendar_id, token)
                delta_by_source[source_key] = delta
                if not bool(delta.get("supported", False)):
                    _audit(
                        calendar_id=calendar_id,
                        uid="calendar",
                        action="sync_token_fallback_window_scan",
                        details={"error": str(delta.get("error", ""))},
                    )

            _ = caldav_service.list_window_index(user_info.calendar_id, window_start, query_window_end)
            user_window_events = caldav_service.fetch_events(user_info.calendar_id, window_start, query_window_end)
            ext_window_events: dict[str, list[EventRecord]] = {}
            for calendar in external_calendars:
                _ = caldav_service.list_window_index(calendar.calendar_id, window_start, query_window_end)
                ext_window_events[calendar.calendar_id] = caldav_service.fetch_events(
                    calendar.calendar_id, window_start, query_window_end
                )
            new_window_events = caldav_service.fetch_events(new_info.calendar_id, window_start, query_window_end)

            for event in user_window_events:
                if event.uid:
                    self.state_store.upsert_snapshot(
                        calendar_id=user_info.calendar_id,
                        uid=event.uid,
                        etag=event.etag,
                        payload_hash=_event_fingerprint(event),
                    )
            for calendar_id, events in ext_window_events.items():
                for event in events:
                    if event.uid:
                        self.state_store.upsert_snapshot(
                            calendar_id=calendar_id,
                            uid=event.uid,
                            etag=event.etag,
                            payload_hash=_event_fingerprint(event),
                        )

            (
                mapping_by_sync,
                mapping_by_source,
                mapping_by_user_uid,
                mapping_by_stack_uid,
            ) = self._load_mapping_indexes()

            now_utc = datetime.now(timezone.utc)
            active_tombstones = {
                (
                    str(item.get("source", "")),
                    str(item.get("source_calendar_id", "")),
                    str(item.get("source_uid", "")),
                )
                for item in self.state_store.list_active_suppression_tombstones(now_iso=now_utc.isoformat())
            }

            stack_state: dict[str, EventRecord] = {}
            deleted_sync_ids: set[str] = set()
            newly_imported_sync_ids: set[str] = set()
            locked_source_calendar_ids = set(config.calendar_rules.locked_calendar_ids or [])
            for calendar in external_calendars:
                if LOCK_NAME_PATTERN.search(str(calendar.name or "")):
                    locked_source_calendar_ids.add(str(calendar.calendar_id))

            for calendar in external_calendars:
                for event in sorted(ext_window_events.get(calendar.calendar_id, []), key=lambda item: (item.uid or "", item.href or "")):
                    if not event.uid:
                        continue
                    if ("ext", calendar.calendar_id, event.uid) in active_tombstones:
                        continue
                    existed = mapping_by_source.get(("ext", calendar.calendar_id, event.uid)) is not None
                    mapping = self._ensure_mapping(
                        source="ext",
                        source_calendar_id=calendar.calendar_id,
                        source_uid=event.uid,
                        preferred_user_uid="",
                        preferred_stack_uid="",
                        by_sync=mapping_by_sync,
                        by_source=mapping_by_source,
                        by_user_uid=mapping_by_user_uid,
                        by_stack_uid=mapping_by_stack_uid,
                    )
                    stack_event = self._stack_event_from_source(
                        source_event=event,
                        mapping=mapping,
                        stack_calendar_id=stack_info.calendar_id,
                    )
                    if calendar.calendar_id in locked_source_calendar_ids:
                        stack_event.locked = True
                    stack_state[str(mapping["sync_id"])] = stack_event
                    if not existed:
                        newly_imported_sync_ids.add(str(mapping["sync_id"]))

            for user_event in sorted(user_window_events, key=lambda item: (item.uid or "", item.href or "")):
                if not user_event.uid:
                    continue
                mapping = None
                if user_event.x_sync_id:
                    mapping = mapping_by_sync.get(str(user_event.x_sync_id))
                if mapping is None:
                    mapping = mapping_by_user_uid.get(user_event.uid)
                if mapping is None:
                    mapping = self._ensure_mapping(
                        source="user",
                        source_calendar_id=user_info.calendar_id,
                        source_uid=user_event.uid,
                        preferred_user_uid=user_event.uid,
                        preferred_stack_uid="",
                        by_sync=mapping_by_sync,
                        by_source=mapping_by_source,
                        by_user_uid=mapping_by_user_uid,
                        by_stack_uid=mapping_by_stack_uid,
                    )
                sync_id = str(mapping["sync_id"])
                if str(mapping.get("user_uid", "")) != user_event.uid:
                    mapping["user_uid"] = user_event.uid
                    self.state_store.upsert_event_mapping(**mapping)
                    self._index_mapping(
                        mapping,
                        by_sync=mapping_by_sync,
                        by_source=mapping_by_source,
                        by_user_uid=mapping_by_user_uid,
                        by_stack_uid=mapping_by_stack_uid,
                    )
                stack_user_event = self._stack_event_from_source(
                    source_event=user_event,
                    mapping=mapping,
                    stack_calendar_id=stack_info.calendar_id,
                )
                if (
                    str(mapping.get("source", "")) == "ext"
                    and str(mapping.get("source_calendar_id", "")) in locked_source_calendar_ids
                ):
                    stack_user_event.locked = True
                existing = stack_state.get(sync_id)
                if existing is None:
                    stack_state[sync_id] = stack_user_event
                else:
                    stack_state[sync_id] = self._merge_user_event_into_stack(existing, stack_user_event)

            user_delta = delta_by_source.get(self._source_key("user", user_info.calendar_id), {})
            for changed_event in user_delta.get("add_update", []):
                if not isinstance(changed_event, EventRecord):
                    continue
                if not changed_event.uid or not self._in_window(changed_event, window_start, window_end):
                    continue
                mapping = mapping_by_user_uid.get(changed_event.uid)
                if mapping is None:
                    mapping = self._ensure_mapping(
                        source="user",
                        source_calendar_id=user_info.calendar_id,
                        source_uid=changed_event.uid,
                        preferred_user_uid=changed_event.uid,
                        preferred_stack_uid="",
                        by_sync=mapping_by_sync,
                        by_source=mapping_by_source,
                        by_user_uid=mapping_by_user_uid,
                        by_stack_uid=mapping_by_stack_uid,
                    )
                sync_id = str(mapping["sync_id"])
                stack_changed = self._stack_event_from_source(
                    source_event=changed_event,
                    mapping=mapping,
                    stack_calendar_id=stack_info.calendar_id,
                )
                if (
                    str(mapping.get("source", "")) == "ext"
                    and str(mapping.get("source_calendar_id", "")) in locked_source_calendar_ids
                ):
                    stack_changed.locked = True
                if sync_id not in stack_state:
                    stack_state[sync_id] = stack_changed
                else:
                    stack_state[sync_id] = self._merge_user_event_into_stack(stack_state[sync_id], stack_changed)

            for deleted_item in user_delta.get("delete", []):
                if not isinstance(deleted_item, dict):
                    continue
                deleted_uid = str(deleted_item.get("uid", "")).strip()
                if not deleted_uid:
                    continue
                mapping = mapping_by_user_uid.get(deleted_uid)
                if mapping is None:
                    continue
                sync_id = str(mapping["sync_id"])
                deleted_sync_ids.add(sync_id)
                self.state_store.set_event_mapping_status(sync_id=sync_id, status="deleted")
                if str(mapping.get("source", "")) == "ext":
                    self.state_store.upsert_suppression_tombstone(
                        source="ext",
                        source_calendar_id=str(mapping.get("source_calendar_id", "")),
                        source_uid=str(mapping.get("source_uid", "")),
                        reason="user_deleted",
                        expires_at=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
                    )

            new_candidates: dict[str, EventRecord] = {}
            for item in new_window_events:
                if item.uid:
                    new_candidates[item.uid] = item
            new_delta = delta_by_source.get(self._source_key("new", new_info.calendar_id), {})
            for item in new_delta.get("add_update", []):
                if isinstance(item, EventRecord) and item.uid:
                    new_candidates[item.uid] = item
            inbox_pending_count = 0

            for item in sorted(new_candidates.values(), key=lambda event: (event.uid or "", event.href or "")):
                if not item.uid or not self._in_window(item, window_start, window_end):
                    continue
                inbox_pending_count += 1
                mapping = mapping_by_source.get(("new", new_info.calendar_id, item.uid))
                if mapping is None:
                    mapping = self._ensure_mapping(
                        source="new",
                        source_calendar_id=new_info.calendar_id,
                        source_uid=item.uid,
                        preferred_user_uid="",
                        preferred_stack_uid="",
                        by_sync=mapping_by_sync,
                        by_source=mapping_by_source,
                        by_user_uid=mapping_by_user_uid,
                        by_stack_uid=mapping_by_stack_uid,
                    )
                sync_id = str(mapping["sync_id"])
                stack_state[sync_id] = self._stack_event_from_source(
                    source_event=item,
                    mapping=mapping,
                    stack_calendar_id=stack_info.calendar_id,
                )
                newly_imported_sync_ids.add(sync_id)
                self.state_store.enqueue_pending_new_cleanup(
                    new_uid=item.uid,
                    new_href=item.href,
                    mapped_sync_id=str(mapping["sync_id"]),
                )

            freeze_cutoff = datetime.now(timezone.utc) + timedelta(hours=max(0, int(config.sync.freeze_hours)))
            planning_events: list[EventRecord] = []
            target_uids: list[str] = []
            target_uid_set: set[str] = set()
            target_intents_by_uid: dict[str, str] = {}
            hash_items: list[dict[str, Any]] = []
            stack_uid_to_sync_id: dict[str, str] = {}
            seen_stage_uids: set[str] = set()
            for sync_id, event in sorted(stack_state.items(), key=lambda pair: pair[0]):
                if sync_id in deleted_sync_ids:
                    continue
                if event.calendar_id != stack_info.calendar_id:
                    continue
                if event.uid and event.uid in seen_stage_uids:
                    continue
                # Ensure managed layers always carry a normalized [AI Task] block.
                normalized_description, normalized_task, description_changed = ensure_ai_task_block(
                    event.description or "",
                    config.task_defaults,
                )
                if bool(normalized_task.get("locked", False)) != bool(event.locked):
                    normalized_description, _, lock_changed = set_ai_task_locked(
                        normalized_description,
                        config.task_defaults,
                        bool(event.locked),
                    )
                    description_changed = bool(description_changed or lock_changed)
                if description_changed:
                    event.description = normalized_description
                planning_events.append(event)
                if event.uid:
                    stack_uid_to_sync_id[event.uid] = sync_id
                    seen_stage_uids.add(event.uid)
                hash_items.append(
                    {
                        "sync_id": sync_id,
                        "uid": event.uid,
                        "summary": event.summary,
                        "description": event.description,
                        "location": event.location,
                        "start": serialize_datetime(event.start),
                        "end": serialize_datetime(event.end),
                        "locked": bool(_event_locked_for_ai(event)),
                    }
                )
                frozen = _event_is_frozen(
                    event,
                    freeze_hours=int(config.sync.freeze_hours),
                    freeze_cutoff=freeze_cutoff,
                )
                has_user_intent = _event_has_user_intent(event)
                is_newly_imported = sync_id in newly_imported_sync_ids
                expired = _event_is_expired(event, now_utc=planning_now)
                if not _event_locked_for_ai(event) and not frozen and not expired and (has_user_intent or is_newly_imported):
                    if has_user_intent:
                        target_intent = _extract_user_intent(event)
                    else:
                        target_intent = "Arrange this newly imported event into the schedule."
                    if event.uid and event.uid not in target_uid_set:
                        target_uid_set.add(event.uid)
                        target_uids.append(event.uid)
                    if event.uid:
                        target_intents_by_uid[event.uid] = target_intent

            overlap_target_uids: set[str] = set()
            planning_events_for_overlap = [item for item in planning_events if item.uid and not item.all_day]
            for idx in range(len(planning_events_for_overlap)):
                left_event = planning_events_for_overlap[idx]
                for jdx in range(idx + 1, len(planning_events_for_overlap)):
                    right_event = planning_events_for_overlap[jdx]
                    if not _event_overlap(left_event, right_event):
                        continue
                    for candidate in (left_event, right_event):
                        if not candidate.uid:
                            continue
                        if _event_locked_for_ai(candidate):
                            continue
                        if _event_is_frozen(
                            candidate,
                            freeze_hours=int(config.sync.freeze_hours),
                            freeze_cutoff=freeze_cutoff,
                        ):
                            continue
                        if _event_is_expired(candidate, now_utc=planning_now):
                            continue
                        overlap_target_uids.add(candidate.uid)

            if overlap_target_uids:
                for uid in sorted(overlap_target_uids):
                    if uid not in target_uid_set:
                        target_uid_set.add(uid)
                        target_uids.append(uid)
                    if not str(target_intents_by_uid.get(uid, "") or "").strip():
                        target_intents_by_uid[uid] = "Resolve schedule overlap conflicts while preserving locked events."
                _audit(
                    calendar_id="system",
                    uid="ai",
                    action="overlap_targets_detected",
                    details={
                        "overlap_target_count": len(overlap_target_uids),
                        "overlap_target_uids": sorted(overlap_target_uids),
                    },
                )

            ai_input_hash = _hash_text(json.dumps(hash_items, ensure_ascii=False, sort_keys=True))
            last_ai_hash = self.state_store.get_meta("last_applied_ai_hash")
            force_ai_due_to_new_inbox = inbox_pending_count > 0
            raw_ai_result: dict[str, Any] = {"changes": [], "creates": []}

            if config.ai.enabled and target_uids and (
                ai_input_hash != last_ai_hash or force_ai_due_to_new_inbox
            ):
                ai_client = OpenAICompatibleClient(config.ai)
                if ai_client.is_configured():
                    base_model = str(config.ai.model or "").strip()
                    selected_model = base_model
                    high_load_model = str(getattr(config.ai, "high_load_model", "") or "").strip()
                    high_load_manual_active = False
                    high_load_auto_enabled = bool(getattr(config.ai, "high_load_auto_enabled", True))
                    high_load_min_event_count = max(1, int(getattr(config.ai, "high_load_min_event_count", 20) or 20))
                    high_load_auto_metrics = _compute_high_load_auto_metrics(
                        planning_events=planning_events,
                        window_start=window_start,
                        window_end=window_end,
                        event_baseline=int(getattr(config.ai, "high_load_auto_event_baseline", 20) or 20),
                        score_threshold=float(getattr(config.ai, "high_load_auto_score_threshold", 0.80) or 0.80),
                    )
                    high_load_auto_active = (
                        high_load_auto_enabled
                        and bool(high_load_auto_metrics.get("active", False))
                        and len(planning_events) >= high_load_min_event_count
                    )
                    high_load_active = high_load_auto_active
                    model_route = "high_load" if bool(high_load_model) and high_load_active else "base"
                    model_route_reason = "base_default"
                    if model_route == "high_load":
                        model_route_reason = "auto_score_threshold_and_min_event_count_met"
                    elif (
                        high_load_auto_enabled
                        and bool(high_load_model)
                        and bool(high_load_auto_metrics.get("active", False))
                        and len(planning_events) < high_load_min_event_count
                    ):
                        model_route_reason = "auto_score_met_but_below_min_event_count"
                    if high_load_model and high_load_active:
                        selected_model = high_load_model
                    use_flex_tier = bool(getattr(config.ai, "high_load_use_flex", False)) and high_load_active
                    configured_reasoning_effort = (
                        str(getattr(config.ai, "high_load_reasoning_effort", "low") or "").strip().lower() or "low"
                    )
                    selected_reasoning_effort = ""
                    if high_load_active and configured_reasoning_effort in {"low", "medium", "high"}:
                        selected_reasoning_effort = configured_reasoning_effort
                    payload_events: list[dict[str, Any]] = []
                    for event in planning_events:
                        visible_description, ai_task, _ = ai_task_payload_from_description(
                            event.description or "",
                            config.task_defaults,
                        )
                        payload_event: dict[str, Any] = {
                            "uid": event.uid,
                            "start": serialize_datetime(event.start) or "",
                            "end": serialize_datetime(event.end) or "",
                            "summary": str(event.summary or ""),
                            "location": str(event.location or ""),
                            "description": visible_description,
                            "all_day": bool(event.all_day),
                            "locked": bool(ai_task.get("locked", event.locked)),
                        }
                        if event.uid in target_uid_set:
                            payload_event["user_intent"] = target_intents_by_uid.get(event.uid, "")
                        payload_events.append(payload_event)
                    payload_event_by_uid: dict[str, dict[str, Any]] = {}
                    for item in payload_events:
                        uid = str(item.get("uid", "") or "").strip()
                        if uid and uid not in payload_event_by_uid:
                            payload_event_by_uid[uid] = item
                    has_new_import_targets = any(
                        bool(stack_uid_to_sync_id.get(uid) in newly_imported_sync_ids)
                        for uid in target_uids
                    )
                    sparse_context_enabled = bool(getattr(config.ai, "sparse_new_event_context_enabled", True))
                    sparse_context_scope = (
                        str(getattr(config.ai, "sparse_context_scope", "all_targets") or "").strip().lower()
                        or "all_targets"
                    )
                    if sparse_context_scope not in {"new_only", "all_targets"}:
                        sparse_context_scope = "all_targets"
                    if sparse_context_scope == "new_only":
                        sparse_mode_active = sparse_context_enabled and has_new_import_targets
                    else:
                        sparse_mode_active = sparse_context_enabled and bool(target_uids)
                    neighbor_count = max(0, int(getattr(config.ai, "sparse_new_event_neighbor_count", 1) or 1))
                    max_context_requests = max(1, int(getattr(config.ai, "sparse_new_event_max_context_requests", 3) or 3))
                    max_full_detail_events = max(
                        1, int(getattr(config.ai, "payload_max_full_detail_events", 10) or 10)
                    )
                    target_description_max_chars = max(
                        1, int(getattr(config.ai, "payload_target_description_max_chars", 160) or 160)
                    )
                    neighbor_description_max_chars = max(
                        1, int(getattr(config.ai, "payload_neighbor_description_max_chars", 80) or 80)
                    )

                    def _invoke_ai_with_payload(payload: dict[str, Any], phase: str) -> dict[str, Any]:
                        messages = build_messages(payload, system_prompt=config.ai.system_prompt)
                        request_payload = {
                            "model": selected_model,
                            "messages": messages,
                            "response_format": {"type": "json_object"},
                        }
                        if not selected_model.startswith("gpt-5"):
                            request_payload["temperature"] = 0.2
                        if selected_reasoning_effort:
                            request_payload["reasoning_effort"] = selected_reasoning_effort
                        if use_flex_tier:
                            request_payload["service_tier"] = "flex"
                        request_bytes = len(json.dumps(request_payload, ensure_ascii=False).encode("utf-8"))
                        client_config = getattr(ai_client, "config", None)
                        if client_config is not None and hasattr(client_config, "model"):
                            original_model = str(getattr(client_config, "model", "") or "").strip()
                            original_service_tier = str(getattr(client_config, "_request_service_tier", "") or "").strip()
                            original_reasoning_effort = str(
                                getattr(client_config, "_request_reasoning_effort", "") or ""
                            ).strip()
                            client_config.model = selected_model
                            client_config._request_service_tier = "flex" if use_flex_tier else ""
                            client_config._request_reasoning_effort = selected_reasoning_effort
                            try:
                                result = ai_client.generate_changes(messages=messages) or {"changes": [], "creates": []}
                            finally:
                                client_config.model = original_model
                                client_config._request_service_tier = original_service_tier
                                client_config._request_reasoning_effort = original_reasoning_effort
                        else:
                            result = ai_client.generate_changes(messages=messages) or {"changes": [], "creates": []}
                        usage = dict(getattr(ai_client, "last_usage", {}) or {})
                        payload_events_by_uid = payload.get("events_by_uid", {}) if isinstance(payload, dict) else {}
                        full_detail_events_count = 0
                        busy_events_count = 0
                        description_chars_sent = 0
                        if isinstance(payload_events_by_uid, dict):
                            for item in payload_events_by_uid.values():
                                if not isinstance(item, dict):
                                    continue
                                if str(item.get("detail_level", "") or "").strip().lower() == "full":
                                    full_detail_events_count += 1
                                else:
                                    busy_events_count += 1
                                description_chars_sent += len(str(item.get("description", "") or ""))
                        payload_char_count = len(json.dumps(payload, ensure_ascii=False))
                        _audit(
                            calendar_id="system",
                            uid="ai",
                            action="ai_request",
                            details={
                                "request_bytes": request_bytes,
                                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                                "total_tokens": int(usage.get("total_tokens", 0) or 0),
                                "target_events_count": len(target_uids),
                                "target_uids_count": len(target_uids),
                                "planning_events_count": len(planning_events),
                                "events_sent_count": len(payload_events_by_uid) if isinstance(payload_events_by_uid, dict) else 0,
                                "payload_char_count": int(payload_char_count),
                                "payload_version": COMPACT_PAYLOAD_VERSION,
                                "planning_phase": phase,
                                "sparse_context_mode": bool(sparse_mode_active),
                                "sparse_context_scope": sparse_context_scope,
                                "inbox_pending_count": int(inbox_pending_count),
                                "forced_by_new_inbox": bool(force_ai_due_to_new_inbox),
                                "ai_input_hash": ai_input_hash,
                                "model": selected_model,
                                "model_route": model_route,
                                "model_route_reason": model_route_reason,
                                "high_load_model_active": bool(selected_model != str(config.ai.model or "").strip()),
                                "high_load_manual_active": high_load_manual_active,
                                "high_load_auto_enabled": high_load_auto_enabled,
                                "high_load_auto_active": high_load_auto_active,
                                "high_load_min_event_count": high_load_min_event_count,
                                "high_load_auto_score": float(high_load_auto_metrics.get("score", 0.0) or 0.0),
                                "high_load_auto_score_threshold": float(
                                    high_load_auto_metrics.get("score_threshold", 0.0) or 0.0
                                ),
                                "high_load_auto_density_ratio": float(
                                    high_load_auto_metrics.get("density_ratio", 0.0) or 0.0
                                ),
                                "high_load_auto_count_ratio": float(
                                    high_load_auto_metrics.get("count_ratio", 0.0) or 0.0
                                ),
                                "high_load_auto_conflict_ratio": float(
                                    high_load_auto_metrics.get("conflict_ratio", 0.0) or 0.0
                                ),
                                "high_load_auto_conflict_pairs": int(
                                    high_load_auto_metrics.get("conflict_pairs", 0) or 0
                                ),
                                "service_tier": "flex" if use_flex_tier else "",
                                "reasoning_effort": selected_reasoning_effort or "",
                                "full_detail_events_count": int(full_detail_events_count),
                                "busy_events_count": int(busy_events_count),
                                "description_chars_sent": int(description_chars_sent),
                            },
                        )
                        return result

                    phase1_full_uids = _build_full_detail_uid_set_for_targets(
                        payload_events=payload_events,
                        target_uids=target_uids,
                        neighbor_count=neighbor_count,
                        max_full_detail_events=max_full_detail_events,
                    )
                    phase1_payload = build_planning_payload(
                        events=None,
                        events_payload=payload_events,
                        window_start=serialize_datetime(window_start) or "",
                        window_end=serialize_datetime(window_end) or "",
                        timezone=effective_timezone,
                        target_uids=target_uids,
                        compact=True,
                        sparse_other_events=sparse_mode_active,
                        full_detail_uids=sorted(phase1_full_uids),
                        target_description_max_chars=target_description_max_chars,
                        neighbor_description_max_chars=neighbor_description_max_chars,
                        planning_phase="phase1",
                        current_time=serialize_datetime(planning_now) or "",
                    )
                    phase1_result = _invoke_ai_with_payload(phase1_payload, "phase1")
                    phase1_plan = normalize_ai_plan_result(phase1_result)
                    context_requests = list(phase1_plan.get("context_requests", []) or [])
                    if sparse_mode_active and not context_requests:
                        forced_dates: set[date] = set()
                        force_phase2 = False
                        phase1_changes = list(phase1_plan.get("changes", []) or [])
                        phase1_creates = list(phase1_plan.get("creates", []) or [])

                        for change in phase1_changes:
                            uid = str(change.get("uid", "") or "").strip()
                            if not uid:
                                continue
                            if uid not in target_uid_set:
                                force_phase2 = True
                            original_item = payload_event_by_uid.get(uid, {})
                            original_range = original_item.get("start", "") if isinstance(original_item, dict) else ""
                            original_day = _extract_iso_day(original_range)
                            proposed_start_day = _extract_iso_day(change.get("start"))
                            proposed_end_day = _extract_iso_day(change.get("end"))
                            if original_day is not None:
                                forced_dates.add(original_day)
                            if proposed_start_day is not None:
                                forced_dates.add(proposed_start_day)
                            if proposed_end_day is not None:
                                forced_dates.add(proposed_end_day)
                            if uid in target_uid_set and proposed_start_day is not None and original_day is not None:
                                if proposed_start_day != original_day:
                                    force_phase2 = True

                        if phase1_creates:
                            force_phase2 = True
                            for create in phase1_creates:
                                parent_uid = str(create.get("from_uid", "") or "").strip()
                                parent_item = payload_event_by_uid.get(parent_uid, {})
                                parent_start = parent_item.get("start", "") if isinstance(parent_item, dict) else ""
                                parent_day = _extract_iso_day(parent_start)
                                if parent_day is not None:
                                    forced_dates.add(parent_day)
                                create_start_day = _extract_iso_day(create.get("start"))
                                create_end_day = _extract_iso_day(create.get("end"))
                                if create_start_day is not None:
                                    forced_dates.add(create_start_day)
                                if create_end_day is not None:
                                    forced_dates.add(create_end_day)

                        if force_phase2:
                            for day in sorted(forced_dates):
                                context_requests.append(
                                    {
                                        "date": day.isoformat(),
                                        "reason": "auto_expand_due_to_sparse_phase1_changes",
                                    }
                                )
                            _audit(
                                calendar_id="system",
                                uid="ai",
                                action="ai_sparse_phase2_forced",
                                details={
                                    "forced_context_count": len(context_requests),
                                    "phase1_change_count": len(phase1_changes),
                                    "phase1_create_count": len(phase1_creates),
                                },
                            )
                    if sparse_mode_active and context_requests:
                        bounded_context_requests = context_requests[:max_context_requests]
                        phase2_full_uids = _expand_full_detail_uids_by_context_requests(
                            payload_events=payload_events,
                            base_full_uids=phase1_full_uids,
                            context_requests=bounded_context_requests,
                            target_uids=target_uids,
                            max_full_detail_events=max_full_detail_events,
                        )
                        phase2_payload = build_planning_payload(
                            events=None,
                            events_payload=payload_events,
                            window_start=serialize_datetime(window_start) or "",
                            window_end=serialize_datetime(window_end) or "",
                            timezone=effective_timezone,
                            target_uids=target_uids,
                            compact=True,
                            sparse_other_events=True,
                            full_detail_uids=sorted(phase2_full_uids),
                            target_description_max_chars=target_description_max_chars,
                            neighbor_description_max_chars=neighbor_description_max_chars,
                            planning_phase="phase2",
                            requested_context=bounded_context_requests,
                            current_time=serialize_datetime(planning_now) or "",
                        )
                        raw_ai_result = _invoke_ai_with_payload(phase2_payload, "phase2")
                    else:
                        raw_ai_result = phase1_result
                else:
                    _audit(calendar_id="system", uid="ai", action="skip_ai_not_configured", details={})
            elif not config.ai.enabled:
                _audit(calendar_id="system", uid="ai", action="skip_ai_disabled", details={})
            elif ai_input_hash == last_ai_hash:
                _audit(
                    calendar_id="system",
                    uid="ai",
                    action="skip_ai_same_input_hash",
                    details={
                        "inbox_pending_count": int(inbox_pending_count),
                        "forced_by_new_inbox": bool(force_ai_due_to_new_inbox),
                    },
                )
            else:
                _audit(calendar_id="system", uid="ai", action="skip_ai_no_targets", details={})

            normalized_plan = normalize_ai_plan_result(raw_ai_result)
            normalized_changes = normalized_plan.get("changes", [])
            normalized_creates = normalized_plan.get("creates", [])
            ai_changed_sync_ids: set[str] = set()
            ai_created_sync_ids: set[str] = set()
            for change in normalized_changes:
                uid = str(change.get("uid", "")).strip()
                if not uid:
                    continue
                sync_id = stack_uid_to_sync_id.get(uid)
                if sync_id is None:
                    user_mapping = mapping_by_user_uid.get(uid)
                    if user_mapping is not None:
                        sync_id = str(user_mapping["sync_id"])
                if sync_id is None or sync_id in deleted_sync_ids:
                    _audit(
                        calendar_id="system",
                        uid="ai",
                        action="ai_change_unmatched",
                        details={"uid": uid, "calendar_id": change.get("calendar_id", "")},
                    )
                    continue
                current_event = stack_state.get(sync_id)
                if current_event is None:
                    continue
                if _event_locked_for_ai(current_event):
                    _audit(
                        calendar_id=current_event.calendar_id,
                        uid=current_event.uid,
                        action="ai_change_skipped_locked",
                        details={},
                    )
                    continue
                if _event_is_expired(current_event, now_utc=planning_now):
                    _audit(
                        calendar_id=current_event.calendar_id,
                        uid=current_event.uid,
                        action="ai_change_skipped_expired_event",
                        details={"now": serialize_datetime(planning_now)},
                    )
                    continue
                frozen = _event_is_frozen(
                    current_event,
                    freeze_hours=int(config.sync.freeze_hours),
                    freeze_cutoff=freeze_cutoff,
                )
                if frozen and ("start" in change or "end" in change):
                    _audit(
                        calendar_id=current_event.calendar_id,
                        uid=current_event.uid,
                        action="ai_change_skipped_freeze_window",
                        details={"freeze_hours": int(config.sync.freeze_hours)},
                    )
                    continue

                outcome = apply_change(
                    current_event=current_event,
                    change=change,
                    baseline_etag="",
                    editable_fields=_extract_editable_fields(current_event, list(config.task_defaults.editable_fields)),
                )
                if outcome.conflicted:
                    conflicts += 1
                    _audit(
                        calendar_id=current_event.calendar_id,
                        uid=current_event.uid,
                        action="conflict",
                        details={"reason": outcome.reason},
                    )
                    continue
                if not outcome.applied:
                    continue
                updated = outcome.event
                changed_fields: list[str] = []
                patch_items: list[dict[str, Any]] = []
                for field_name in ("start", "end", "summary", "location", "description"):
                    before_value = getattr(current_event, field_name)
                    after_value = getattr(updated, field_name)
                    if before_value == after_value:
                        continue
                    changed_fields.append(field_name)
                    if field_name in {"start", "end"}:
                        patch_items.append(
                            {
                                "field": field_name,
                                "before": serialize_datetime(before_value),
                                "after": serialize_datetime(after_value),
                            }
                        )
                    else:
                        patch_items.append(
                            {
                                "field": field_name,
                                "before": str(before_value or ""),
                                "after": str(after_value or ""),
                            }
                        )
                updated.x_sync_id = current_event.x_sync_id
                updated.x_source = current_event.x_source
                updated.x_source_uid = current_event.x_source_uid
                updated.original_calendar_id = current_event.original_calendar_id
                updated.original_uid = current_event.original_uid
                # After an AI-applied change, clear user_intent to prevent repeated triggering.
                updated_description, _, _ = set_ai_task_user_intent(
                    updated.description or "",
                    config.task_defaults,
                    "",
                )
                updated.description = updated_description
                stack_state[sync_id] = updated
                ai_changed_sync_ids.add(sync_id)
                _audit(
                    calendar_id=current_event.calendar_id,
                    uid=current_event.uid,
                    action="apply_ai_change",
                    details={
                        "reason": str(change.get("reason", "") or "").strip(),
                        "fields": changed_fields,
                        "patch": patch_items,
                        "before_event": current_event.to_dict(),
                        "after_event": updated.to_dict(),
                    },
                )

            max_creates_per_run = 20
            max_split_segments = 3
            max_create_segments_per_parent = max(0, max_split_segments - 1)
            creates_by_parent: dict[str, int] = {}
            creates_to_apply = normalized_creates[:max_creates_per_run]
            if len(normalized_creates) > max_creates_per_run:
                _audit(
                    calendar_id="system",
                    uid="ai",
                    action="ai_create_truncated",
                    details={
                        "reason": "max_creates_per_run",
                        "received_count": len(normalized_creates),
                        "accepted_count": len(creates_to_apply),
                        "max_creates_per_run": max_creates_per_run,
                    },
                )
            for create in creates_to_apply:
                from_uid = str(create.get("from_uid", "") or "").strip()
                if not from_uid:
                    continue
                parent_sync_id = stack_uid_to_sync_id.get(from_uid)
                if parent_sync_id is None:
                    user_mapping = mapping_by_user_uid.get(from_uid)
                    if user_mapping is not None:
                        parent_sync_id = str(user_mapping.get("sync_id", ""))
                if not parent_sync_id or parent_sync_id in deleted_sync_ids:
                    _audit(
                        calendar_id="system",
                        uid="ai",
                        action="ai_create_invalid_parent",
                        details={"from_uid": from_uid, "reason": "parent_not_found"},
                    )
                    continue
                parent_event = stack_state.get(parent_sync_id)
                if parent_event is None:
                    _audit(
                        calendar_id="system",
                        uid="ai",
                        action="ai_create_invalid_parent",
                        details={"from_uid": from_uid, "reason": "parent_event_missing"},
                    )
                    continue
                if _event_locked_for_ai(parent_event):
                    _audit(
                        calendar_id=parent_event.calendar_id,
                        uid=parent_event.uid,
                        action="ai_create_invalid_parent",
                        details={"from_uid": from_uid, "reason": "parent_locked"},
                    )
                    continue
                if _event_is_expired(parent_event, now_utc=planning_now):
                    _audit(
                        calendar_id=parent_event.calendar_id,
                        uid=parent_event.uid,
                        action="ai_create_invalid_parent",
                        details={"from_uid": from_uid, "reason": "parent_expired"},
                    )
                    continue
                current_parent_create_count = int(creates_by_parent.get(from_uid, 0) or 0)
                if current_parent_create_count >= max_create_segments_per_parent:
                    _audit(
                        calendar_id="system",
                        uid="ai",
                        action="ai_create_truncated",
                        details={
                            "from_uid": from_uid,
                            "reason": "max_split_segments",
                            "max_split_segments": max_split_segments,
                        },
                    )
                    continue
                try:
                    created_start = parse_iso_datetime(create.get("start"))
                    created_end = parse_iso_datetime(create.get("end"))
                except Exception:
                    created_start = None
                    created_end = None
                if created_start is None or created_end is None or created_end <= created_start:
                    _audit(
                        calendar_id="system",
                        uid="ai",
                        action="ai_create_invalid_datetime",
                        details={
                            "from_uid": from_uid,
                            "start": create.get("start"),
                            "end": create.get("end"),
                        },
                    )
                    continue
                create_key = str(create.get("create_key", "") or "").strip() or f"part-{current_parent_create_count + 2}"
                summary = str(create.get("summary", "") or parent_event.summary or "").strip()
                location = str(create.get("location", "") or "").strip()
                description = str(create.get("description", "") or "").strip()
                source_uid_seed = "|".join(
                    [
                        create_key,
                        from_uid,
                        serialize_datetime(created_start) or "",
                        serialize_datetime(created_end) or "",
                        summary,
                    ]
                )
                source_uid = "ai-" + hashlib.sha1(source_uid_seed.encode("utf-8")).hexdigest()
                mapping = self._ensure_mapping(
                    source="ai",
                    source_calendar_id=stack_info.calendar_id,
                    source_uid=source_uid,
                    preferred_user_uid="",
                    preferred_stack_uid="",
                    by_sync=mapping_by_sync,
                    by_source=mapping_by_source,
                    by_user_uid=mapping_by_user_uid,
                    by_stack_uid=mapping_by_stack_uid,
                )
                if str(mapping.get("status", "active")) != "active":
                    mapping["status"] = "active"
                    self.state_store.upsert_event_mapping(**mapping)
                    self._index_mapping(
                        mapping,
                        by_sync=mapping_by_sync,
                        by_source=mapping_by_source,
                        by_user_uid=mapping_by_user_uid,
                        by_stack_uid=mapping_by_stack_uid,
                    )
                sync_id = str(mapping["sync_id"])
                deleted_sync_ids.discard(sync_id)

                created_event = EventRecord(
                    calendar_id=stack_info.calendar_id,
                    uid=str(mapping["stack_uid"]),
                    summary=summary,
                    description=description,
                    location=location,
                    start=created_start,
                    end=created_end,
                    source="stack",
                    x_sync_id=sync_id,
                    x_source="ai",
                    x_source_uid=source_uid,
                    locked=False,
                    original_calendar_id=stack_info.calendar_id,
                    original_uid=source_uid,
                )
                normalized_description, _, _ = ensure_ai_task_block(
                    created_event.description or "",
                    config.task_defaults,
                )
                normalized_description, _, _ = set_ai_task_locked(
                    normalized_description,
                    config.task_defaults,
                    False,
                )
                normalized_description, _, _ = set_ai_task_user_intent(
                    normalized_description,
                    config.task_defaults,
                    "",
                )
                created_event.description = normalized_description

                stack_state[sync_id] = created_event
                stack_uid_to_sync_id[created_event.uid] = sync_id
                ai_created_sync_ids.add(sync_id)
                creates_by_parent[from_uid] = current_parent_create_count + 1
                _audit(
                    calendar_id=created_event.calendar_id,
                    uid=created_event.uid,
                    action="apply_ai_create",
                    details={
                        "from_uid": from_uid,
                        "create_key": create_key,
                        "reason": str(create.get("reason", "") or "").strip(),
                        "event": created_event.to_dict(),
                    },
                )

            desired_stack_by_uid: dict[str, tuple[str, EventRecord]] = {}
            desired_user_by_uid: dict[str, tuple[str, EventRecord]] = {}
            processed_sync_ids: set[str] = set()

            for sync_id, mapping in mapping_by_sync.items():
                if sync_id in deleted_sync_ids or str(mapping.get("status", "active")) == "deleted":
                    processed_sync_ids.add(sync_id)
                    continue
                event = stack_state.get(sync_id)
                if event is None:
                    continue
                in_window = self._in_window(event, window_start, window_end)
                include_due_to_ai_change = sync_id in ai_changed_sync_ids or sync_id in ai_created_sync_ids
                if not in_window and not include_due_to_ai_change:
                    continue

                processed_sync_ids.add(sync_id)
                stack_event = event.clone().with_updates(
                    calendar_id=stack_info.calendar_id,
                    uid=str(mapping["stack_uid"]),
                    x_sync_id=str(sync_id),
                    x_source=self._source_label(mapping),
                    x_source_uid=str(mapping["source_uid"]),
                    original_calendar_id=str(mapping["source_calendar_id"]),
                    original_uid=str(mapping["source_uid"]),
                )
                user_event = event.clone().with_updates(
                    calendar_id=user_info.calendar_id,
                    uid=str(mapping["user_uid"]),
                    x_sync_id=str(sync_id),
                    x_source=self._source_label(mapping),
                    x_source_uid=str(mapping["source_uid"]),
                    original_calendar_id=str(mapping["source_calendar_id"]),
                    original_uid=str(mapping["source_uid"]),
                )
                desired_stack_by_uid[stack_event.uid] = (sync_id, stack_event)
                desired_user_by_uid[user_event.uid] = (sync_id, user_event)

            current_stack_events = caldav_service.fetch_events(stack_info.calendar_id, window_start, query_window_end)
            current_user_events = caldav_service.fetch_events(user_info.calendar_id, window_start, query_window_end)
            current_stack_by_uid = {event.uid: event for event in current_stack_events if event.uid}
            current_user_by_uid = {event.uid: event for event in current_user_events if event.uid}
            failed_sync_ids: set[str] = set()

            for uid, (sync_id, desired_event) in desired_stack_by_uid.items():
                current_event = current_stack_by_uid.get(uid)
                if current_event is not None and self._events_equal(current_event, desired_event):
                    continue
                ok, saved = self._apply_upsert_with_retry(
                    caldav_service=caldav_service,
                    calendar_id=stack_info.calendar_id,
                    desired_event=desired_event,
                    current_event=current_event,
                )
                if not ok:
                    failed_sync_ids.add(sync_id)
                    conflicts += 1
                    _audit(
                        calendar_id=stack_info.calendar_id,
                        uid=uid,
                        action="conflict",
                        details={"reason": "stack_upsert_failed"},
                    )
                    continue
                changes_applied += 1
                if saved is not None:
                    current_stack_by_uid[uid] = saved

            for uid, current_event in current_stack_by_uid.items():
                mapping = mapping_by_stack_uid.get(uid)
                if mapping is None and not current_event.x_sync_id:
                    continue
                if uid in desired_stack_by_uid:
                    continue
                sync_id = str(mapping["sync_id"]) if mapping is not None else str(current_event.x_sync_id)
                if self._apply_delete_with_retry(
                    caldav_service=caldav_service,
                    calendar_id=stack_info.calendar_id,
                    uid=uid,
                    href=current_event.href,
                    expected_etag=current_event.etag,
                ):
                    changes_applied += 1
                else:
                    failed_sync_ids.add(sync_id)
                    conflicts += 1
                    _audit(
                        calendar_id=stack_info.calendar_id,
                        uid=uid,
                        action="conflict",
                        details={"reason": "stack_delete_failed"},
                    )

            failed_user_upserts: list[tuple[str, str, EventRecord]] = []
            for uid, (sync_id, desired_event) in desired_user_by_uid.items():
                if sync_id in deleted_sync_ids:
                    continue
                current_event = current_user_by_uid.get(uid)
                if current_event is not None and self._events_equal(current_event, desired_event):
                    continue
                ok, saved = self._apply_upsert_with_retry(
                    caldav_service=caldav_service,
                    calendar_id=user_info.calendar_id,
                    desired_event=desired_event,
                    current_event=current_event,
                )
                if not ok:
                    failed_user_upserts.append((uid, sync_id, desired_event))
                    failed_sync_ids.add(sync_id)
                    conflicts += 1
                    _audit(
                        calendar_id=user_info.calendar_id,
                        uid=uid,
                        action="conflict",
                        details={"reason": "user_upsert_failed"},
                    )
                    continue
                changes_applied += 1
                if saved is not None:
                    current_user_by_uid[uid] = saved

            # Concurrency safeguard: if user calendar changed while waiting AI, retry failed
            # upserts once more with the latest remote event state.
            for uid, sync_id, desired_event in failed_user_upserts:
                latest_event = caldav_service.get_event_by_uid(user_info.calendar_id, uid)
                ok, saved = self._apply_upsert_with_retry(
                    caldav_service=caldav_service,
                    calendar_id=user_info.calendar_id,
                    desired_event=desired_event,
                    current_event=latest_event,
                )
                if not ok:
                    continue
                if sync_id in failed_sync_ids and conflicts > 0:
                    failed_sync_ids.discard(sync_id)
                    conflicts -= 1
                changes_applied += 1
                if saved is not None:
                    current_user_by_uid[uid] = saved
                _audit(
                    calendar_id=user_info.calendar_id,
                    uid=uid,
                    action="user_upsert_retry_recovered",
                    details={"sync_id": sync_id},
                )

            for sync_id in deleted_sync_ids:
                mapping = mapping_by_sync.get(sync_id)
                if mapping is None:
                    continue
                uid = str(mapping.get("user_uid", ""))
                current_event = current_user_by_uid.get(uid)
                if not uid or current_event is None:
                    continue
                if self._apply_delete_with_retry(
                    caldav_service=caldav_service,
                    calendar_id=user_info.calendar_id,
                    uid=uid,
                    href=current_event.href,
                    expected_etag=current_event.etag,
                ):
                    changes_applied += 1
                else:
                    failed_sync_ids.add(sync_id)
                    conflicts += 1
                    _audit(
                        calendar_id=user_info.calendar_id,
                        uid=uid,
                        action="conflict",
                        details={"reason": "user_delete_failed"},
                    )

            for sync_id in processed_sync_ids:
                self.state_store.set_event_mapping_status(
                    sync_id=sync_id,
                    status=("deleted" if sync_id in deleted_sync_ids else "active"),
                )

            successful_sync_ids = {sync_id for sync_id in processed_sync_ids if sync_id not in failed_sync_ids}
            for item in self.state_store.list_pending_new_cleanup():
                mapped_sync_id = str(item.get("mapped_sync_id", ""))
                if mapped_sync_id not in successful_sync_ids:
                    continue
                new_uid = str(item.get("new_uid", ""))
                new_href = str(item.get("new_href", ""))
                delete_ok = caldav_service.delete_event(new_info.calendar_id, uid=new_uid, href=new_href)
                still_exists = caldav_service.get_event_by_uid(new_info.calendar_id, new_uid)
                if delete_ok or still_exists is None:
                    self.state_store.dequeue_pending_new_cleanup(new_uid=new_uid)

            for source_key, delta in delta_by_source.items():
                if not bool(delta.get("supported", False)):
                    continue
                next_token = str(delta.get("next_token", "")).strip()
                if next_token:
                    self.state_store.set_sync_token(source_key=source_key, sync_token=next_token)

            if config.ai.enabled:
                # Persist hash of post-AI state to avoid retriggering on AI's own writeback.
                final_hash_items: list[dict[str, Any]] = []
                for sync_id, event in sorted(stack_state.items(), key=lambda pair: pair[0]):
                    if sync_id in deleted_sync_ids:
                        continue
                    final_hash_items.append(
                        {
                            "sync_id": sync_id,
                            "uid": event.uid,
                            "summary": event.summary,
                            "description": event.description,
                            "location": event.location,
                            "start": serialize_datetime(event.start),
                            "end": serialize_datetime(event.end),
                            "locked": bool(_event_locked_for_ai(event)),
                        }
                    )
                final_ai_hash = _hash_text(json.dumps(final_hash_items, ensure_ascii=False, sort_keys=True))
                self.state_store.set_meta("last_applied_ai_hash", final_ai_hash)

            duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
            message = f"Processed {len(processed_sync_ids)} sync items."
            self.state_store.finish_sync_run(
                run_id=run_id,
                status="success",
                message=message,
                duration_ms=duration_ms,
                changes_applied=changes_applied,
                conflicts=conflicts,
            )
            return SyncResult(
                status="success",
                message=f"{message} run_id={run_id}",
                duration_ms=duration_ms,
                changes_applied=changes_applied,
                conflicts=conflicts,
                trigger=trigger,
            )
        except Exception as exc:
            duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
            error_message = f"{type(exc).__name__}: {exc}"
            self.state_store.finish_sync_run(
                run_id=run_id,
                status="error",
                message=error_message,
                duration_ms=duration_ms,
                changes_applied=changes_applied,
                conflicts=conflicts,
            )
            self.state_store.record_audit_event(
                calendar_id="system",
                uid="sync",
                action="run_error",
                details={
                    "trigger": trigger,
                    "error": error_message,
                    "traceback": traceback.format_exc(limit=5),
                },
                run_id=run_id,
            )
            return SyncResult(
                status="error",
                message=error_message,
                duration_ms=duration_ms,
                changes_applied=changes_applied,
                conflicts=conflicts,
                trigger=trigger,
            )
