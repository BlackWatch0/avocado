from __future__ import annotations

import hashlib
import json
import re
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
from avocado.task_block import (
    ensure_ai_task_block,
    parse_ai_task_block,
    set_ai_task_category,
    set_ai_task_user_intent,
)


def _hash_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()  # nosec B324


def _staging_uid(calendar_id: str, uid: str) -> str:
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
    # Keep exactly one namespace prefix (the right-most managed prefix).
    return ":".join(parts[depth - 1 :])


def _event_fingerprint(event: EventRecord) -> str:
    return _hash_text(
        f"{event.summary}|{event.description}|{event.location}|"
        f"{serialize_datetime(event.start)}|{serialize_datetime(event.end)}"
    )


def _event_has_user_intent(event: EventRecord) -> bool:
    parsed = parse_ai_task_block(event.description or "")
    if isinstance(parsed, dict):
        return bool(str(parsed.get("user_intent", "")).strip())

    # Fallback for manually edited blocks that are temporarily invalid YAML.
    description = event.description or ""
    block_match = re.search(r"\[AI Task\]\s*\n(.*?)\n\[/AI Task\]", description, re.DOTALL)
    if not block_match:
        return False
    raw_block = block_match.group(1)
    intent_match = re.search(r"^\s*user_intent\s*:\s*(.+)\s*$", raw_block, re.MULTILINE)
    if not intent_match:
        return False
    value = intent_match.group(1).strip()
    if value in {"", "\"\"", "''", "null", "None", "~"}:
        return False
    return True


def _extract_user_intent(event: EventRecord) -> str:
    parsed = parse_ai_task_block(event.description or "")
    if isinstance(parsed, dict):
        return str(parsed.get("user_intent", "")).strip()
    description = event.description or ""
    block_match = re.search(r"\[AI Task\]\s*\n(.*?)\n\[/AI Task\]", description, re.DOTALL)
    if not block_match:
        return ""
    raw_block = block_match.group(1)
    intent_match = re.search(r"^\s*user_intent\s*:\s*(.+)\s*$", raw_block, re.MULTILINE)
    if not intent_match:
        return ""
    value = intent_match.group(1).strip()
    if value in {"", "\"\"", "''", "null", "None", "~"}:
        return ""
    return value


def _extract_editable_fields(event: EventRecord, fallback_fields: list[str]) -> list[str]:
    parsed = parse_ai_task_block(event.description or "")
    if isinstance(parsed, dict):
        editable_fields = parsed.get("editable_fields")
        if isinstance(editable_fields, list):
            cleaned = [str(field).strip() for field in editable_fields if str(field).strip()]
            if cleaned:
                return cleaned
    return [str(field).strip() for field in fallback_fields if str(field).strip()]


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


def _event_patch(before: EventRecord, after: EventRecord) -> list[dict[str, str]]:
    fields = ["summary", "start", "end", "location", "description"]
    patches: list[dict[str, str]] = []
    for field in fields:
        if field in {"start", "end"}:
            before_val = serialize_datetime(getattr(before, field))
            after_val = serialize_datetime(getattr(after, field))
        else:
            before_val = str(getattr(before, field) or "")
            after_val = str(getattr(after, field) or "")
        if before_val != after_val:
            patches.append(
                {
                    "field": field,
                    "before": str(before_val or ""),
                    "after": str(after_val or ""),
                }
            )
    return patches


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
        preserve_uid: bool = False,
    ) -> EventRecord:
        target_uid = source_event.uid if preserve_uid else _staging_uid(source_event.calendar_id, source_event.uid)
        staging_event = source_event.with_updates(
            calendar_id=staging_calendar_id,
            uid=target_uid,
            href="",
            source="staging",
            original_calendar_id=source_event.calendar_id,
            original_uid=source_event.uid,
        )
        return caldav_service.upsert_event(staging_calendar_id, staging_event)

    def run_once(
        self,
        trigger: str = "manual",
        window_start_override: datetime | None = None,
        window_end_override: datetime | None = None,
    ) -> SyncResult:
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
            per_calendar_defaults = config.calendar_rules.per_calendar_defaults

            staging_info = caldav_service.ensure_staging_calendar(
                config.calendar_rules.staging_calendar_id,
                config.calendar_rules.staging_calendar_name,
            )
            user_info = caldav_service.ensure_staging_calendar(
                config.calendar_rules.user_calendar_id,
                config.calendar_rules.user_calendar_name,
            )
            intake_info = caldav_service.ensure_staging_calendar(
                config.calendar_rules.intake_calendar_id,
                config.calendar_rules.intake_calendar_name,
            )
            calendar_rule_updates: dict[str, Any] = {}
            if config.calendar_rules.staging_calendar_id != staging_info.calendar_id:
                calendar_rule_updates["staging_calendar_id"] = staging_info.calendar_id
            if config.calendar_rules.user_calendar_id != user_info.calendar_id:
                calendar_rule_updates["user_calendar_id"] = user_info.calendar_id
            if config.calendar_rules.intake_calendar_id != intake_info.calendar_id:
                calendar_rule_updates["intake_calendar_id"] = intake_info.calendar_id
            if calendar_rule_updates:
                self.config_manager.update({"calendar_rules": calendar_rule_updates})
                config = self.config_manager.load()
                per_calendar_defaults = config.calendar_rules.per_calendar_defaults

            calendars = caldav_service.list_calendars()
            managed_name_keys = {
                _normalize_calendar_name(config.calendar_rules.staging_calendar_name),
                _normalize_calendar_name(config.calendar_rules.user_calendar_name),
                _normalize_calendar_name(config.calendar_rules.intake_calendar_name),
            }
            managed_name_keys.discard("")
            managed_calendar_ids = {staging_info.calendar_id, user_info.calendar_id, intake_info.calendar_id}
            for calendar in calendars:
                if calendar.calendar_id in managed_calendar_ids:
                    continue
                normalized_name = _normalize_calendar_name(calendar.name)
                if normalized_name in managed_name_keys or any(
                    normalized_name.startswith(f"{key} ") or normalized_name.startswith(f"{key}(")
                    for key in managed_name_keys
                ):
                    managed_calendar_ids.add(calendar.calendar_id)
                    self.state_store.record_audit_event(
                        calendar_id=calendar.calendar_id,
                        uid="calendar",
                        action="skip_managed_duplicate_calendar",
                        details={
                            "trigger": trigger,
                            "name": calendar.name,
                            "reason": "same_name_as_managed_calendar",
                        },
                    )

            suggested_immutable = caldav_service.suggest_immutable_calendar_ids(
                calendars, config.calendar_rules.immutable_keywords
            )
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
            ) - editable_override - managed_calendar_ids

            if (window_start_override is None) ^ (window_end_override is None):
                raise ValueError("window_start_override and window_end_override must both be provided")
            if window_start_override is not None and window_end_override is not None:
                window_start = window_start_override.astimezone(timezone.utc)
                window_end = window_end_override.astimezone(timezone.utc)
                if window_end < window_start:
                    raise ValueError("window_end_override must be later than window_start_override")
            else:
                window_start, window_end = planning_window(
                    datetime.now(timezone.utc), config.sync.window_days
                )

            all_events: list[EventRecord] = []
            mutable_events: dict[tuple[str, str], EventRecord] = {}
            baseline_etags: dict[tuple[str, str], str] = {}
            should_replan = trigger in {"manual", "startup"}

            duplicate_user_calendars: list[tuple[str, str]] = []
            duplicate_stage_calendars: list[tuple[str, str]] = []
            duplicate_intake_calendars: list[tuple[str, str]] = []
            normalized_user_name = _normalize_calendar_name(config.calendar_rules.user_calendar_name)
            normalized_stage_name = _normalize_calendar_name(config.calendar_rules.staging_calendar_name)
            normalized_intake_name = _normalize_calendar_name(config.calendar_rules.intake_calendar_name)
            for calendar in calendars:
                if calendar.calendar_id in {user_info.calendar_id, staging_info.calendar_id, intake_info.calendar_id}:
                    continue
                name_key = _normalize_calendar_name(calendar.name)
                if normalized_user_name and name_key == normalized_user_name:
                    duplicate_user_calendars.append((calendar.calendar_id, calendar.name))
                elif normalized_stage_name and name_key == normalized_stage_name:
                    duplicate_stage_calendars.append((calendar.calendar_id, calendar.name))
                elif normalized_intake_name and name_key == normalized_intake_name:
                    duplicate_intake_calendars.append((calendar.calendar_id, calendar.name))

            for duplicate_id, duplicate_name in duplicate_user_calendars:
                duplicate_events = caldav_service.fetch_events(duplicate_id, window_start, window_end)
                for duplicate_event in duplicate_events:
                    if not duplicate_event.uid:
                        continue
                    delete_ok = caldav_service.delete_event(
                        duplicate_id,
                        uid=duplicate_event.uid,
                        href=duplicate_event.href,
                    )
                    self.state_store.record_audit_event(
                        calendar_id=duplicate_id,
                        uid=duplicate_event.uid,
                        action="purge_duplicate_user_calendar_event",
                        details={
                            "trigger": trigger,
                            "delete_ok": delete_ok,
                            "duplicate_calendar_name": duplicate_name,
                        },
                    )
                    should_replan = True

            for duplicate_id, duplicate_name in duplicate_stage_calendars:
                duplicate_events = caldav_service.fetch_events(duplicate_id, window_start, window_end)
                for duplicate_event in duplicate_events:
                    if not duplicate_event.uid:
                        continue
                    delete_ok = caldav_service.delete_event(
                        duplicate_id,
                        uid=duplicate_event.uid,
                        href=duplicate_event.href,
                    )
                    self.state_store.record_audit_event(
                        calendar_id=duplicate_id,
                        uid=duplicate_event.uid,
                        action="purge_duplicate_stage_calendar_event",
                        details={
                            "trigger": trigger,
                            "delete_ok": delete_ok,
                            "duplicate_calendar_name": duplicate_name,
                        },
                    )
                    should_replan = True

            for duplicate_id, duplicate_name in duplicate_intake_calendars:
                duplicate_events = caldav_service.fetch_events(duplicate_id, window_start, window_end)
                for duplicate_event in duplicate_events:
                    if not duplicate_event.uid:
                        continue
                    delete_ok = caldav_service.delete_event(
                        duplicate_id,
                        uid=duplicate_event.uid,
                        href=duplicate_event.href,
                    )
                    self.state_store.record_audit_event(
                        calendar_id=duplicate_id,
                        uid=duplicate_event.uid,
                        action="purge_duplicate_intake_calendar_event",
                        details={
                            "trigger": trigger,
                            "delete_ok": delete_ok,
                            "duplicate_calendar_name": duplicate_name,
                        },
                    )
                    should_replan = True

            stage_events = caldav_service.fetch_events(
                staging_info.calendar_id, window_start, window_end
            )
            stage_map: dict[str, EventRecord] = {}
            for stage_event in sorted(stage_events, key=lambda item: ((item.uid or ""), (item.href or ""))):
                if not stage_event.uid:
                    continue
                if _managed_uid_prefix_depth(stage_event.uid) >= 2:
                    delete_ok = caldav_service.delete_event(
                        staging_info.calendar_id,
                        uid=stage_event.uid,
                        href=stage_event.href,
                    )
                    self.state_store.record_audit_event(
                        calendar_id=staging_info.calendar_id,
                        uid=stage_event.uid,
                        action="purge_nested_stage_uid",
                        details={"trigger": trigger, "delete_ok": delete_ok},
                    )
                    should_replan = True
                    continue
                if stage_event.uid in stage_map:
                    delete_ok = caldav_service.delete_event(
                        staging_info.calendar_id,
                        uid=stage_event.uid,
                        href=stage_event.href,
                    )
                    self.state_store.record_audit_event(
                        calendar_id=staging_info.calendar_id,
                        uid=stage_event.uid,
                        action="dedupe_stage_uid",
                        details={"trigger": trigger, "delete_ok": delete_ok},
                    )
                    should_replan = True
                    continue
                stage_map[stage_event.uid] = stage_event
            seen_stage_uids: set[str] = set()
            user_events = caldav_service.fetch_events(user_info.calendar_id, window_start, window_end)
            user_map: dict[str, EventRecord] = {}
            for user_event in sorted(user_events, key=lambda item: ((item.uid or ""), (item.href or ""))):
                if not user_event.uid:
                    continue
                if _managed_uid_prefix_depth(user_event.uid) >= 2:
                    legacy_nested_uid = user_event.uid
                    collapsed_uid = _collapse_nested_managed_uid(user_event.uid)
                    if collapsed_uid != user_event.uid:
                        existing_collapsed = user_map.get(collapsed_uid)
                        if existing_collapsed is None:
                            existing_collapsed = caldav_service.get_event_by_uid(user_info.calendar_id, collapsed_uid)
                        if existing_collapsed is not None:
                            delete_ok = caldav_service.delete_event(
                                user_info.calendar_id,
                                uid=user_event.uid,
                                href=user_event.href,
                            )
                            user_map[collapsed_uid] = existing_collapsed
                            self.state_store.record_audit_event(
                                calendar_id=user_info.calendar_id,
                                uid=legacy_nested_uid,
                                action="purge_nested_user_uid",
                                details={
                                    "trigger": trigger,
                                    "collapsed_uid": collapsed_uid,
                                    "delete_ok": delete_ok,
                                },
                            )
                            should_replan = True
                            continue
                        migrated_user = user_event.with_updates(
                            calendar_id=user_info.calendar_id,
                            uid=collapsed_uid,
                            href="",
                            source="user",
                        )
                        try:
                            migrated_user = caldav_service.upsert_event(user_info.calendar_id, migrated_user)
                            delete_ok = caldav_service.delete_event(
                                user_info.calendar_id,
                                uid=user_event.uid,
                                href=user_event.href,
                            )
                            user_event = migrated_user
                            self.state_store.record_audit_event(
                                calendar_id=user_info.calendar_id,
                                uid=collapsed_uid,
                                action="collapse_nested_user_uid",
                                details={
                                    "trigger": trigger,
                                    "legacy_uid": legacy_nested_uid,
                                    "collapsed_uid": collapsed_uid,
                                    "delete_ok": delete_ok,
                                },
                            )
                            should_replan = True
                        except Exception:
                            delete_ok = caldav_service.delete_event(
                                user_info.calendar_id,
                                uid=user_event.uid,
                                href=user_event.href,
                            )
                            self.state_store.record_audit_event(
                                calendar_id=user_info.calendar_id,
                                uid=legacy_nested_uid,
                                action="purge_invalid_nested_user_uid",
                                details={
                                    "trigger": trigger,
                                    "legacy_uid": legacy_nested_uid,
                                    "collapsed_uid": collapsed_uid,
                                    "delete_ok": delete_ok,
                                },
                            )
                            should_replan = True
                            continue

                if user_event.uid in user_map:
                    delete_ok = caldav_service.delete_event(
                        user_info.calendar_id,
                        uid=user_event.uid,
                        href=user_event.href,
                    )
                    self.state_store.record_audit_event(
                        calendar_id=user_info.calendar_id,
                        uid=user_event.uid,
                        action="dedupe_user_uid",
                        details={"trigger": trigger, "delete_ok": delete_ok},
                    )
                    should_replan = True
                    continue

                user_map[user_event.uid] = user_event

            intake_events = caldav_service.fetch_events(intake_info.calendar_id, window_start, window_end)
            for intake_event in sorted(intake_events, key=lambda item: ((item.uid or ""), (item.href or ""))):
                if not intake_event.uid:
                    continue
                intake_uid_depth = _managed_uid_prefix_depth(intake_event.uid)
                # Intake calendar should only contain raw user-created events (no managed UID prefix).
                # Managed-prefixed entries are leftovers and must be purged to avoid re-import loops.
                if intake_uid_depth >= 1:
                    delete_ok = caldav_service.delete_event(
                        intake_info.calendar_id,
                        uid=intake_event.uid,
                        href=intake_event.href,
                    )
                    self.state_store.record_audit_event(
                        calendar_id=intake_info.calendar_id,
                        uid=intake_event.uid,
                        action="purge_managed_intake_uid",
                        details={
                            "trigger": trigger,
                            "uid_depth": intake_uid_depth,
                            "delete_ok": delete_ok,
                        },
                    )
                    continue

                user_uid = _staging_uid(intake_info.calendar_id, intake_event.uid)
                existing_user = user_map.get(user_uid)
                if existing_user is not None:
                    delete_ok = caldav_service.delete_event(
                        intake_info.calendar_id,
                        uid=intake_event.uid,
                        href=intake_event.href,
                    )
                    self.state_store.record_audit_event(
                        calendar_id=intake_info.calendar_id,
                        uid=intake_event.uid,
                        action="intake_event_already_imported",
                        details={
                            "trigger": trigger,
                            "mapped_user_uid": user_uid,
                            "delete_ok": delete_ok,
                        },
                    )
                    continue

                imported_user = intake_event.with_updates(
                    calendar_id=user_info.calendar_id,
                    uid=user_uid,
                    href="",
                    source="user",
                    original_calendar_id=intake_info.calendar_id,
                    original_uid=intake_event.uid,
                )
                try:
                    imported_user = caldav_service.upsert_event(user_info.calendar_id, imported_user)
                except Exception as exc:
                    if "Duplicate entry" in str(exc) or "Integrity constraint violation" in str(exc):
                        delete_ok = caldav_service.delete_event(
                            intake_info.calendar_id,
                            uid=intake_event.uid,
                            href=intake_event.href,
                        )
                        existing_by_uid = caldav_service.get_event_by_uid(user_info.calendar_id, user_uid)
                        if existing_by_uid is not None:
                            user_map[user_uid] = existing_by_uid
                        self.state_store.record_audit_event(
                            calendar_id=user_info.calendar_id,
                            uid=user_uid,
                            action="skip_intake_uid_conflict",
                            details={
                                "trigger": trigger,
                                "delete_ok": delete_ok,
                                "recovered_existing_user": existing_by_uid is not None,
                            },
                        )
                        continue
                    raise

                delete_ok = caldav_service.delete_event(
                    intake_info.calendar_id,
                    uid=intake_event.uid,
                    href=intake_event.href,
                )
                user_map[user_uid] = imported_user
                should_replan = True
                self.state_store.record_audit_event(
                    calendar_id=intake_info.calendar_id,
                    uid=intake_event.uid,
                    action="import_intake_event_to_user_layer",
                    details={
                        "trigger": trigger,
                        "mapped_user_uid": user_uid,
                        "delete_ok": delete_ok,
                    },
                )

            for calendar in calendars:
                if calendar.calendar_id in managed_calendar_ids:
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

                        # Seed user-layer event from non-stage/non-user calendars if missing.
                        if _managed_uid_prefix_depth(event.uid) >= 2:
                            self.state_store.record_audit_event(
                                calendar_id=calendar.calendar_id,
                                uid=event.uid,
                                action="skip_nested_source_uid",
                                details={"trigger": trigger},
                            )
                        else:
                            user_uid = _staging_uid(calendar.calendar_id, event.uid)
                            seeded_user = user_map.get(user_uid)
                            legacy_user = user_map.get(event.uid)
                            if legacy_user is not None and user_uid != event.uid:
                                # Migrate legacy plain UID user events to the namespaced UID to prevent duplicates.
                                migrated = legacy_user.with_updates(
                                    uid=user_uid,
                                    href="",
                                    calendar_id=user_info.calendar_id,
                                    source="user",
                                    original_calendar_id=calendar.calendar_id,
                                    original_uid=event.uid,
                                )
                                try:
                                    migrated = caldav_service.upsert_event(user_info.calendar_id, migrated)
                                except Exception as exc:
                                    if "Duplicate entry" in str(exc) or "Integrity constraint violation" in str(exc):
                                        self.state_store.record_audit_event(
                                            calendar_id=user_info.calendar_id,
                                            uid=user_uid,
                                            action="skip_seed_uid_conflict",
                                            details={
                                                "trigger": trigger,
                                                "reason": "duplicate_uid_on_migrate",
                                            },
                                        )
                                        user_map.pop(legacy_user.uid, None)
                                        seeded_user = user_map.get(user_uid)
                                        continue
                                    raise
                                user_map[user_uid] = migrated
                                delete_ok = caldav_service.delete_event(
                                    user_info.calendar_id,
                                    uid=legacy_user.uid,
                                    href=legacy_user.href,
                                )
                                # Ensure the legacy entry is not processed again in this run.
                                user_map.pop(legacy_user.uid, None)
                                self.state_store.record_audit_event(
                                    calendar_id=user_info.calendar_id,
                                    uid=user_uid,
                                    action="migrate_user_uid",
                                    details={
                                        "trigger": trigger,
                                        "legacy_uid": legacy_user.uid,
                                        "new_uid": user_uid,
                                        "delete_ok": delete_ok,
                                    },
                                )
                                seeded_user = migrated
                            if seeded_user is None:
                                seeded_user = event.with_updates(
                                    calendar_id=user_info.calendar_id,
                                    uid=user_uid,
                                    href="",
                                    source="user",
                                    original_calendar_id=calendar.calendar_id,
                                    original_uid=event.uid,
                                )
                                try:
                                    seeded_user = caldav_service.upsert_event(user_info.calendar_id, seeded_user)
                                except Exception as exc:
                                    if "Duplicate entry" in str(exc) or "Integrity constraint violation" in str(exc):
                                        self.state_store.record_audit_event(
                                            calendar_id=user_info.calendar_id,
                                            uid=user_uid,
                                            action="skip_seed_uid_conflict",
                                            details={
                                                "trigger": trigger,
                                                "reason": "duplicate_uid_on_seed",
                                            },
                                        )
                                        continue
                                    raise
                                user_map[user_uid] = seeded_user
                                should_replan = True
                            # Propagate user_intent edits from source calendars to mapped user-layer event.
                            source_intent = _extract_user_intent(event)
                            if seeded_user is not None and source_intent:
                                target_intent = _extract_user_intent(seeded_user)
                                if source_intent != target_intent:
                                    new_description, _, intent_changed = set_ai_task_user_intent(
                                        seeded_user.description,
                                        config.task_defaults,
                                        source_intent,
                                    )
                                    if intent_changed:
                                        seeded_user.description = new_description
                                        seeded_user = caldav_service.upsert_event(user_info.calendar_id, seeded_user)
                                        user_map[user_uid] = seeded_user
                                        should_replan = True
                                        self.state_store.record_audit_event(
                                            calendar_id=user_info.calendar_id,
                                            uid=user_uid,
                                            action="propagate_user_intent_from_source",
                                            details={
                                                "trigger": trigger,
                                                "source_calendar_id": calendar.calendar_id,
                                                "source_uid": event.uid,
                                            },
                                        )

                    # Planning payload should include immutable constraints, while editable
                    # source events are represented by user-layer mirrors to avoid duplicates.
                    if calendar_is_immutable:
                        all_events.append(event)
                    self.state_store.upsert_snapshot(
                        calendar_id=calendar.calendar_id,
                        uid=event.uid,
                        etag=event.etag,
                        payload_hash=_hash_text(
                            f"{event.summary}|{event.description}|{serialize_datetime(event.start)}|{serialize_datetime(event.end)}"
                        ),
                    )

            # User-layer events are the editable working set.
            for user_event in list(user_map.values()):
                behavior = per_calendar_defaults.get(user_info.calendar_id, {})
                task_defaults = TaskDefaultsConfig(
                    locked=bool(behavior.get("locked", config.task_defaults.locked)),
                    mandatory=bool(behavior.get("mandatory", config.task_defaults.mandatory)),
                    editable_fields=list(config.task_defaults.editable_fields),
                )
                new_description, task_payload, changed = ensure_ai_task_block(user_event.description, task_defaults)
                user_event.description = new_description
                user_event.locked = bool(task_payload.get("locked", task_defaults.locked))
                user_event.mandatory = bool(task_payload.get("mandatory", task_defaults.mandatory))
                if changed:
                    user_event = caldav_service.upsert_event(user_info.calendar_id, user_event)
                    user_map[user_event.uid] = user_event
                    should_replan = True
                    self.state_store.record_audit_event(
                        calendar_id=user_info.calendar_id,
                        uid=user_event.uid,
                        action="seed_or_normalize_ai_task",
                        details={"trigger": trigger, "layer": "user-layer"},
                    )

                seen_stage_uids.add(user_event.uid)
                stage_event = stage_map.get(user_event.uid)
                if stage_event is None or _event_fingerprint(stage_event) != _event_fingerprint(user_event):
                    should_replan = True

                mutable_events[(user_info.calendar_id, user_event.uid)] = user_event
                baseline_etags[(user_info.calendar_id, user_event.uid)] = user_event.etag
                all_events.append(user_event)

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
                # Skip scheduled AI calls when planning payload is unchanged.
                if trigger == "scheduled":
                    payload_fingerprint = _hash_text(
                        json.dumps(planning_payload, ensure_ascii=False, sort_keys=True)
                    )
                    last_payload_fingerprint = self.state_store.get_meta("last_planning_payload_fingerprint")
                    if payload_fingerprint == last_payload_fingerprint:
                        self.state_store.record_audit_event(
                            calendar_id="system",
                            uid="ai",
                            action="skip_ai_same_payload",
                            details={"trigger": trigger},
                        )
                        should_replan = False
                    else:
                        self.state_store.set_meta("last_planning_payload_fingerprint", payload_fingerprint)
            if ai_client.is_configured() and should_replan:
                messages = build_messages(planning_payload, system_prompt=config.ai.system_prompt)
                ai_request_payload = {
                    "model": config.ai.model,
                    "messages": messages,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                }
                ai_request_bytes = len(json.dumps(ai_request_payload, ensure_ascii=False).encode("utf-8"))
                self.state_store.record_audit_event(
                    calendar_id="system",
                    uid="ai",
                    action="ai_request",
                    details={
                        "trigger": trigger,
                        "request_bytes": ai_request_bytes,
                        "messages_count": len(messages),
                        "events_count": len(all_events),
                    },
                )
                ai_output = ai_client.generate_changes(messages=messages)
                raw_changes = ai_output.get("changes", [])
                self.state_store.record_audit_event(
                    calendar_id="system",
                    uid="ai",
                    action="ai_response",
                    details={
                        "trigger": trigger,
                        "raw_changes_count": len(raw_changes),
                        "preview": raw_changes[:10],
                    },
                )

            normalized_changes = normalize_changes(raw_changes)

            for change in normalized_changes:
                target_key = (change["calendar_id"], change["uid"])
                event = mutable_events.get(target_key)
                if event is None:
                    # Map source-layer uid to user-layer uid if AI picked source calendar.
                    mapped_user_uid = _staging_uid(change["calendar_id"], change["uid"])
                    event = mutable_events.get((user_info.calendar_id, mapped_user_uid))
                if event is None:
                    # UID fallback for providers that omit calendar_id correctly in AI response.
                    candidates = [x for k, x in mutable_events.items() if k[1] == change["uid"]]
                    event = candidates[0] if len(candidates) == 1 else None
                if event is None:
                    self.state_store.record_audit_event(
                        calendar_id="system",
                        uid="ai",
                        action="ai_change_unmatched",
                        details={
                            "trigger": trigger,
                            "calendar_id": change.get("calendar_id"),
                            "uid": change.get("uid"),
                        },
                    )
                    continue

                if not _event_has_user_intent(event):
                    self.state_store.record_audit_event(
                        calendar_id=event.calendar_id,
                        uid=event.uid,
                        action="ai_change_skipped_no_intent",
                        details={"trigger": trigger},
                    )
                    continue

                key = (event.calendar_id, event.uid)
                editable_fields = _extract_editable_fields(event, list(config.task_defaults.editable_fields))
                outcome = apply_change(
                    current_event=event,
                    change=change,
                    baseline_etag=baseline_etags.get(key, ""),
                    editable_fields=editable_fields,
                )
                if outcome.blocked_fields:
                    self.state_store.record_audit_event(
                        calendar_id=event.calendar_id,
                        uid=event.uid,
                        action="ai_change_blocked_by_editable_fields",
                        details={
                            "trigger": trigger,
                            "blocked_fields": outcome.blocked_fields,
                            "editable_fields": editable_fields,
                        },
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

                before_event = event.clone()
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
                patch_fields = _event_patch(before_event, saved_user_event)
                if not patch_fields:
                    # AI already converged; consume intent to prevent repeated no-op replans.
                    no_effect_description, _, no_effect_intent_changed = set_ai_task_user_intent(
                        saved_user_event.description,
                        config.task_defaults,
                        "",
                    )
                    if no_effect_intent_changed:
                        saved_user_event.description = no_effect_description
                        saved_user_event = caldav_service.upsert_event(event.calendar_id, saved_user_event)
                        mutable_events[key] = saved_user_event
                        baseline_etags[key] = saved_user_event.etag
                    self.state_store.record_audit_event(
                        calendar_id=event.calendar_id,
                        uid=event.uid,
                        action="ai_change_skipped_no_effect",
                        details={"trigger": trigger},
                    )
                    continue
                mutable_events[key] = saved_user_event
                baseline_etags[key] = saved_user_event.etag
                changes_applied += 1
                reason_text = str(change.get("reason", "")).strip()
                if not reason_text:
                    reason_text = f"AI adjusted fields: {', '.join(item['field'] for item in patch_fields)}"
                # Consume intent after successful AI apply to avoid re-applying the same instruction.
                consumed_description, _, consumed_intent_changed = set_ai_task_user_intent(
                    saved_user_event.description,
                    config.task_defaults,
                    "",
                )
                if consumed_intent_changed:
                    saved_user_event.description = consumed_description
                    saved_user_event = caldav_service.upsert_event(event.calendar_id, saved_user_event)
                    mutable_events[key] = saved_user_event
                    baseline_etags[key] = saved_user_event.etag
                self.state_store.record_audit_event(
                    calendar_id=event.calendar_id,
                    uid=event.uid,
                    action="apply_ai_change",
                    details={
                        "trigger": trigger,
                        "category": category,
                        "reason": reason_text,
                        "title": saved_user_event.summary,
                        "start": serialize_datetime(saved_user_event.start),
                        "end": serialize_datetime(saved_user_event.end),
                        "fields": [item["field"] for item in patch_fields],
                        "patch": patch_fields,
                        "before_event": before_event.to_dict(),
                        "after_event": saved_user_event.to_dict(),
                    },
                )

            # Stage layer holds AI-processed baseline for next diff.
            for user_event in mutable_events.values():
                try:
                    self._mirror_to_staging(
                        caldav_service=caldav_service,
                        staging_calendar_id=staging_info.calendar_id,
                        source_event=user_event,
                        preserve_uid=True,
                    )
                except Exception as exc:
                    err_text = str(exc)
                    duplicate_uid_error = (
                        "Duplicate entry" in err_text
                        or "Integrity constraint violation" in err_text
                        or "calobjects_by_uid_index" in err_text
                    )
                    if not duplicate_uid_error:
                        raise
                    delete_ok = caldav_service.delete_event(
                        staging_info.calendar_id,
                        uid=user_event.uid,
                    )
                    self.state_store.record_audit_event(
                        calendar_id=staging_info.calendar_id,
                        uid=user_event.uid,
                        action="repair_stage_duplicate_uid",
                        details={
                            "trigger": trigger,
                            "delete_ok": delete_ok,
                        },
                    )
                    if not delete_ok:
                        continue
                    try:
                        self._mirror_to_staging(
                            caldav_service=caldav_service,
                            staging_calendar_id=staging_info.calendar_id,
                            source_event=user_event,
                            preserve_uid=True,
                        )
                    except Exception as retry_exc:
                        self.state_store.record_audit_event(
                            calendar_id=staging_info.calendar_id,
                            uid=user_event.uid,
                            action="skip_stage_mirror_after_duplicate",
                            details={
                                "trigger": trigger,
                                "error": f"{type(retry_exc).__name__}: {retry_exc}",
                            },
                        )
                        continue

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
