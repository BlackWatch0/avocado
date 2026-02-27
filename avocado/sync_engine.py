from __future__ import annotations

import hashlib
import traceback
from datetime import datetime, timezone
from typing import Any

from avocado.ai_client import OpenAICompatibleClient
from avocado.caldav_client import CalDAVService
from avocado.config_manager import ConfigManager
from avocado.models import (
    EventRecord,
    SyncResult,
    TaskDefaultsConfig,
    planning_window,
    serialize_datetime,
)
from avocado.planner import build_messages, build_planning_payload, normalize_changes
from avocado.reconciler import apply_change
from avocado.state_store import StateStore
from avocado.task_block import ensure_ai_task_block, set_ai_task_category


def _hash_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()  # nosec B324


def _staging_uid(calendar_id: str, uid: str) -> str:
    prefix = hashlib.sha1(calendar_id.encode("utf-8")).hexdigest()[:10]  # nosec B324
    return f"{prefix}:{uid}"


def _event_fingerprint(event: EventRecord) -> str:
    return _hash_text(
        f"{event.summary}|{event.description}|{event.location}|"
        f"{serialize_datetime(event.start)}|{serialize_datetime(event.end)}"
    )


def _infer_category(event: EventRecord, change: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(change.get("category", "")),
            str(change.get("summary", event.summary)),
            str(change.get("description", event.description)),
            str(change.get("reason", "")),
        ]
    ).lower()
    if any(k in text for k in ["class", "课程", "lecture", "school", "study"]):
        return "study"
    if any(k in text for k in ["meeting", "会议", "sync", "review", "standup"]):
        return "meeting"
    if any(k in text for k in ["gym", "workout", "exercise", "健身", "跑步"]):
        return "health"
    if any(k in text for k in ["travel", "trip", "flight", "出行", "航班"]):
        return "travel"
    if any(k in text for k in ["family", "home", "家庭", "父母"]):
        return "family"
    return "general"


class SyncEngine:
    def __init__(self, config_manager: ConfigManager, state_store: StateStore) -> None:
        self.config_manager = config_manager
        self.state_store = state_store

    def _mirror_to_staging(
        self,
        *,
        caldav_service: CalDAVService,
        staging_calendar_id: str,
        source_event: EventRecord,
    ) -> EventRecord:
        staging_event = source_event.with_updates(
            calendar_id=staging_calendar_id,
            uid=_staging_uid(source_event.calendar_id, source_event.uid),
            href="",
            source="staging",
            original_calendar_id=source_event.calendar_id,
            original_uid=source_event.uid,
        )
        return caldav_service.upsert_event(staging_calendar_id, staging_event)

    def run_once(self, trigger: str = "manual") -> SyncResult:
        started_at = datetime.now(timezone.utc)
        changes_applied = 0
        conflicts = 0

        try:
            config = self.config_manager.load()
            if not config.caldav.base_url or not config.caldav.username:
                duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
                message = "CalDAV config missing base_url/username. Sync skipped."
                self.state_store.record_sync_run(
                    trigger=trigger,
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
            suggested_immutable = caldav_service.suggest_immutable_calendar_ids(
                calendars, config.calendar_rules.immutable_keywords
            )
            per_calendar_defaults = config.calendar_rules.per_calendar_defaults
            immutable_from_defaults = {
                cid
                for cid, behavior in per_calendar_defaults.items()
                if str(behavior.get("mode", "editable")).lower() == "immutable"
            }
            editable_override = {
                cid
                for cid, behavior in per_calendar_defaults.items()
                if str(behavior.get("mode", "editable")).lower() == "editable"
            }
            immutable_calendar_ids = (
                set(config.calendar_rules.immutable_calendar_ids)
                | suggested_immutable
                | immutable_from_defaults
            ) - editable_override

            staging_info = caldav_service.ensure_staging_calendar(
                config.calendar_rules.staging_calendar_id,
                config.calendar_rules.staging_calendar_name,
            )
            if config.calendar_rules.staging_calendar_id != staging_info.calendar_id:
                self.config_manager.update(
                    {"calendar_rules": {"staging_calendar_id": staging_info.calendar_id}}
                )

            window_start, window_end = planning_window(
                datetime.now(timezone.utc), config.sync.window_days
            )

            all_events: list[EventRecord] = []
            mutable_events: dict[tuple[str, str], EventRecord] = {}
            baseline_etags: dict[tuple[str, str], str] = {}
            should_replan = trigger in {"manual", "startup"}
            stage_events = caldav_service.fetch_events(
                staging_info.calendar_id, window_start, window_end
            )
            stage_map = {evt.uid: evt for evt in stage_events if evt.uid}
            seen_stage_uids: set[str] = set()

            for calendar in calendars:
                if calendar.calendar_id == staging_info.calendar_id:
                    continue

                events = caldav_service.fetch_events(calendar.calendar_id, window_start, window_end)
                calendar_is_immutable = calendar.calendar_id in immutable_calendar_ids
                for event in events:
                    if not event.uid:
                        continue

                    if calendar_is_immutable:
                        behavior = per_calendar_defaults.get(calendar.calendar_id, {})
                        task_defaults = TaskDefaultsConfig(
                            locked=bool(behavior.get("locked", True)),
                            mandatory=bool(behavior.get("mandatory", True)),
                            editable_fields=list(config.task_defaults.editable_fields),
                        )
                        new_description, task_payload, changed = ensure_ai_task_block(
                            event.description,
                            task_defaults,
                        )
                        event.description = new_description
                        event.locked = bool(task_payload.get("locked", True))
                        event.mandatory = bool(task_payload.get("mandatory", True))

                        if changed:
                            event = caldav_service.upsert_event(calendar.calendar_id, event)
                            self.state_store.record_audit_event(
                                calendar_id=calendar.calendar_id,
                                uid=event.uid,
                                action="seed_or_normalize_ai_task",
                                details={"trigger": trigger, "layer": "immutable"},
                            )
                    else:
                        behavior = per_calendar_defaults.get(calendar.calendar_id, {})
                        task_defaults = TaskDefaultsConfig(
                            locked=bool(behavior.get("locked", config.task_defaults.locked)),
                            mandatory=bool(behavior.get("mandatory", config.task_defaults.mandatory)),
                            editable_fields=list(config.task_defaults.editable_fields),
                        )
                        new_description, task_payload, changed = ensure_ai_task_block(
                            event.description,
                            task_defaults,
                        )
                        event.description = new_description
                        event.locked = bool(task_payload.get("locked", task_defaults.locked))
                        event.mandatory = bool(task_payload.get("mandatory", task_defaults.mandatory))

                        if changed:
                            event = caldav_service.upsert_event(calendar.calendar_id, event)
                            self.state_store.record_audit_event(
                                calendar_id=calendar.calendar_id,
                                uid=event.uid,
                                action="seed_or_normalize_ai_task",
                                details={"trigger": trigger, "layer": "user"},
                            )

                        stage_uid = _staging_uid(calendar.calendar_id, event.uid)
                        seen_stage_uids.add(stage_uid)
                        stage_event = stage_map.get(stage_uid)
                        if stage_event is None or _event_fingerprint(stage_event) != _event_fingerprint(event):
                            should_replan = True

                        mutable_events[(calendar.calendar_id, event.uid)] = event
                        baseline_etags[(calendar.calendar_id, event.uid)] = event.etag

                    all_events.append(event)
                    self.state_store.upsert_snapshot(
                        calendar_id=calendar.calendar_id,
                        uid=event.uid,
                        etag=event.etag,
                        payload_hash=_hash_text(
                            f"{event.summary}|{event.description}|{serialize_datetime(event.start)}|{serialize_datetime(event.end)}"
                        ),
                    )

            # If stage has events missing from current user layer, trigger a replan.
            for stage_uid in stage_map.keys():
                if stage_uid not in seen_stage_uids:
                    should_replan = True
                    break

            ai_client = OpenAICompatibleClient(config.ai)
            raw_changes: list[dict[str, Any]] = []
            if ai_client.is_configured() and should_replan:
                planning_payload = build_planning_payload(
                    events=all_events,
                    immutable_calendar_ids=sorted(immutable_calendar_ids),
                    window_start=serialize_datetime(window_start) or "",
                    window_end=serialize_datetime(window_end) or "",
                    timezone=config.sync.timezone,
                )
                messages = build_messages(planning_payload, system_prompt=config.ai.system_prompt)
                ai_output = ai_client.generate_changes(messages=messages)
                raw_changes = ai_output.get("changes", [])

            normalized_changes = normalize_changes(raw_changes)

            for change in normalized_changes:
                target_key = (change["calendar_id"], change["uid"])
                event = mutable_events.get(target_key)
                if event is None:
                    # UID fallback for providers that omit calendar_id correctly in AI response.
                    candidates = [x for k, x in mutable_events.items() if k[1] == change["uid"]]
                    event = candidates[0] if len(candidates) == 1 else None
                if event is None:
                    continue

                key = (event.calendar_id, event.uid)
                outcome = apply_change(
                    current_event=event,
                    change=change,
                    baseline_etag=baseline_etags.get(key, ""),
                )
                if outcome.conflicted:
                    conflicts += 1
                    self.state_store.record_audit_event(
                        calendar_id=event.calendar_id,
                        uid=event.uid,
                        action="conflict",
                        details={"reason": outcome.reason, "trigger": trigger},
                    )
                    continue
                if not outcome.applied:
                    continue

                saved_user_event = caldav_service.upsert_event(event.calendar_id, outcome.event)
                category = str(change.get("category", "")).strip() or _infer_category(saved_user_event, change)
                new_description, _, category_changed = set_ai_task_category(
                    saved_user_event.description,
                    config.task_defaults,
                    category,
                )
                if category_changed:
                    saved_user_event.description = new_description
                    saved_user_event = caldav_service.upsert_event(event.calendar_id, saved_user_event)
                mutable_events[key] = saved_user_event
                baseline_etags[key] = saved_user_event.etag
                changes_applied += 1
                self.state_store.record_audit_event(
                    calendar_id=event.calendar_id,
                    uid=event.uid,
                    action="apply_ai_change",
                    details={
                        "trigger": trigger,
                        "category": category,
                        "fields": sorted([field for field in change.keys() if field not in {"calendar_id", "uid"}]),
                    },
                )

            # Stage layer holds AI-processed baseline for next diff.
            for user_event in mutable_events.values():
                self._mirror_to_staging(
                    caldav_service=caldav_service,
                    staging_calendar_id=staging_info.calendar_id,
                    source_event=user_event,
                )

            duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
            message = f"Processed {len(all_events)} events, {len(normalized_changes)} AI changes."
            run_id = self.state_store.record_sync_run(
                trigger=trigger,
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
            self.state_store.record_sync_run(
                trigger=trigger,
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
            )
            return SyncResult(
                status="error",
                message=error_message,
                duration_ms=duration_ms,
                changes_applied=changes_applied,
                conflicts=conflicts,
                trigger=trigger,
            )
