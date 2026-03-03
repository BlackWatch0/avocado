from __future__ import annotations

import json
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any

from avocado.ai_client import OpenAICompatibleClient
from avocado.core.models import EventRecord, SyncResult, serialize_datetime
from avocado.integrations.caldav import CalDAVService
from avocado.planner import build_messages, build_planning_payload, normalize_changes
from avocado.reconciler import apply_change
from avocado.sync.helpers_identity import _event_fingerprint, _hash_text
from avocado.sync.helpers_intent import (
    _event_has_user_intent,
    _event_locked_for_ai,
    _extract_editable_fields,
    _extract_user_intent,
)
from avocado.task_block import ai_task_payload_from_description, ensure_ai_task_block, set_ai_task_user_intent
from avocado.timezone_utils import resolve_effective_timezone


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
            locked_source_calendar_ids = set(config.calendar_rules.locked_calendar_ids or [])

            for calendar in external_calendars:
                for event in sorted(ext_window_events.get(calendar.calendar_id, []), key=lambda item: (item.uid or "", item.href or "")):
                    if not event.uid:
                        continue
                    if ("ext", calendar.calendar_id, event.uid) in active_tombstones:
                        continue
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
            newly_imported_sync_ids: set[str] = set()
            for item in new_window_events:
                if item.uid:
                    new_candidates[item.uid] = item
            new_delta = delta_by_source.get(self._source_key("new", new_info.calendar_id), {})
            for item in new_delta.get("add_update", []):
                if isinstance(item, EventRecord) and item.uid:
                    new_candidates[item.uid] = item

            for item in sorted(new_candidates.values(), key=lambda event: (event.uid or "", event.href or "")):
                if not item.uid or not self._in_window(item, window_start, window_end):
                    continue
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
            target_events_payload: list[dict[str, Any]] = []
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
                normalized_description, _, description_changed = ensure_ai_task_block(
                    event.description or "",
                    config.task_defaults,
                )
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
                frozen = (
                    bool(config.sync.freeze_hours)
                    and event.start is not None
                    and event.start.astimezone(timezone.utc) <= freeze_cutoff
                )
                has_user_intent = _event_has_user_intent(event)
                is_newly_imported = sync_id in newly_imported_sync_ids
                if not _event_locked_for_ai(event) and not frozen and (has_user_intent or is_newly_imported):
                    if has_user_intent:
                        target_intent = _extract_user_intent(event)
                    else:
                        target_intent = "Arrange this newly imported event into the schedule."
                    target_events_payload.append(
                        {
                            "calendar_id": event.calendar_id,
                            "uid": event.uid,
                            "user_intent": target_intent,
                            "editable_fields": _extract_editable_fields(event, list(config.task_defaults.editable_fields)),
                        }
                    )

            ai_input_hash = _hash_text(json.dumps(hash_items, ensure_ascii=False, sort_keys=True))
            last_ai_hash = self.state_store.get_meta("last_applied_ai_hash")
            raw_changes: list[dict[str, Any]] = []
            payload_calendar_to_real: dict[str, str] = {}

            if config.ai.enabled and target_events_payload and ai_input_hash != last_ai_hash:
                ai_client = OpenAICompatibleClient(config.ai)
                if ai_client.is_configured():
                    selected_model = str(config.ai.model or "").strip()
                    high_load_model = str(getattr(config.ai, "high_load_model", "") or "").strip()
                    high_load_threshold = int(getattr(config.ai, "high_load_event_threshold", 0) or 0)
                    if high_load_model and high_load_threshold > 0 and len(planning_events) >= high_load_threshold:
                        selected_model = high_load_model
                    payload_calendar_to_real = {"stack": stack_info.calendar_id}
                    real_to_payload_calendar = {v: k for k, v in payload_calendar_to_real.items()}
                    payload_events: list[dict[str, Any]] = []
                    for event in planning_events:
                        payload_event = event.with_updates(
                            calendar_id=real_to_payload_calendar.get(event.calendar_id, event.calendar_id)
                        ).to_dict()
                        visible_description, ai_task, x_task_meta = ai_task_payload_from_description(
                            event.description or "",
                            config.task_defaults,
                        )
                        payload_event["description"] = visible_description
                        payload_event["ai_task"] = ai_task
                        payload_event.update(x_task_meta)
                        payload_events.append(payload_event)
                    payload = build_planning_payload(
                        events=None,
                        events_payload=payload_events,
                        window_start=serialize_datetime(window_start) or "",
                        window_end=serialize_datetime(window_end) or "",
                        timezone=effective_timezone,
                        target_events=None,
                    )
                    messages = build_messages(payload, system_prompt=config.ai.system_prompt)
                    request_payload = {
                        "model": selected_model,
                        "messages": messages,
                        "temperature": 0.2,
                        "response_format": {"type": "json_object"},
                    }
                    request_bytes = len(json.dumps(request_payload, ensure_ascii=False).encode("utf-8"))
                    client_config = getattr(ai_client, "config", None)
                    if client_config is not None and hasattr(client_config, "model"):
                        original_model = str(getattr(client_config, "model", "") or "").strip()
                        client_config.model = selected_model
                        try:
                            raw_changes = (ai_client.generate_changes(messages=messages) or {}).get("changes", [])
                        finally:
                            client_config.model = original_model
                    else:
                        raw_changes = (ai_client.generate_changes(messages=messages) or {}).get("changes", [])
                    for change in raw_changes:
                        if not isinstance(change, dict):
                            continue
                        payload_calendar_id = str(change.get("calendar_id", "")).strip()
                        if payload_calendar_id in payload_calendar_to_real:
                            change["calendar_id"] = payload_calendar_to_real[payload_calendar_id]
                    usage = dict(getattr(ai_client, "last_usage", {}) or {})
                    _audit(
                        calendar_id="system",
                        uid="ai",
                        action="ai_request",
                        details={
                            "request_bytes": request_bytes,
                            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                            "total_tokens": int(usage.get("total_tokens", 0) or 0),
                            "target_events_count": len(target_events_payload),
                            "planning_events_count": len(planning_events),
                            "ai_input_hash": ai_input_hash,
                            "model": selected_model,
                            "high_load_model_active": bool(selected_model != str(config.ai.model or "").strip()),
                        },
                    )
                else:
                    _audit(calendar_id="system", uid="ai", action="skip_ai_not_configured", details={})
            elif not config.ai.enabled:
                _audit(calendar_id="system", uid="ai", action="skip_ai_disabled", details={})
            elif ai_input_hash == last_ai_hash:
                _audit(calendar_id="system", uid="ai", action="skip_ai_same_input_hash", details={})
            else:
                _audit(calendar_id="system", uid="ai", action="skip_ai_no_targets", details={})

            normalized_changes = normalize_changes(raw_changes)
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
                frozen = (
                    bool(config.sync.freeze_hours)
                    and current_event.start is not None
                    and current_event.start.astimezone(timezone.utc) <= freeze_cutoff
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
                if not self._in_window(event, window_start, window_end):
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
