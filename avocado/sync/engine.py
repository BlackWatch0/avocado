from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from avocado.config_manager import ConfigManager
from avocado.core.models import EventRecord
from avocado.persistence.state_store import StateStore
from avocado.sync.helpers_identity import _hash_text
from avocado.sync.writeback import WritebackMixin
from avocado.sync.pipeline import PipelineMixin

class SyncEngine(WritebackMixin, PipelineMixin):
    ENGINE_SCHEMA_VERSION = "2"
    ROLLOUT_MODE = "stack_v2"

    def __init__(self, config_manager: ConfigManager, state_store: StateStore) -> None:
        self.config_manager = config_manager
        self.state_store = state_store

    @staticmethod
    def _source_key(source: str, calendar_id: str) -> str:
        return f"{source}:{calendar_id}"

    @staticmethod
    def _stack_uid(sync_id: str) -> str:
        return f"avo-{sync_id}"

    @staticmethod
    def _window_bounds(
        *,
        window_days: int,
        timezone_name: str,
        start_override: datetime | None,
        end_override: datetime | None,
    ) -> tuple[datetime, datetime]:
        if (start_override is None) ^ (end_override is None):
            raise ValueError("window_start_override and window_end_override must both be provided")
        if start_override is not None and end_override is not None:
            start_utc = start_override.astimezone(timezone.utc)
            end_utc = end_override.astimezone(timezone.utc)
            if end_utc <= start_utc:
                raise ValueError("window_end_override must be later than window_start_override")
            return start_utc, end_utc

        try:
            local_tz = ZoneInfo(str(timezone_name or "UTC"))
        except Exception:
            local_tz = ZoneInfo("UTC")
        now_local = datetime.now(local_tz)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=max(1, int(window_days)))
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    @staticmethod
    def _query_window_end(window_start: datetime, window_end: datetime) -> datetime:
        if window_end <= window_start:
            return window_start
        return window_end - timedelta(microseconds=1)

    @staticmethod
    def _in_window(event: EventRecord, window_start: datetime, window_end: datetime) -> bool:
        if event.start is None:
            return False
        start_utc = event.start.astimezone(timezone.utc)
        return window_start <= start_utc < window_end

    @staticmethod
    def _index_mapping(
        row: dict[str, Any],
        *,
        by_sync: dict[str, dict[str, Any]],
        by_source: dict[tuple[str, str, str], dict[str, Any]],
        by_user_uid: dict[str, dict[str, Any]],
        by_stack_uid: dict[str, dict[str, Any]],
    ) -> None:
        by_sync[str(row["sync_id"])] = row
        by_source[
            (
                str(row["source"]),
                str(row["source_calendar_id"]),
                str(row["source_uid"]),
            )
        ] = row
        if str(row.get("user_uid", "")).strip():
            by_user_uid[str(row["user_uid"])] = row
        if str(row.get("stack_uid", "")).strip():
            by_stack_uid[str(row["stack_uid"])] = row

    def _load_mapping_indexes(
        self,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[tuple[str, str, str], dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
    ]:
        by_sync: dict[str, dict[str, Any]] = {}
        by_source: dict[tuple[str, str, str], dict[str, Any]] = {}
        by_user_uid: dict[str, dict[str, Any]] = {}
        by_stack_uid: dict[str, dict[str, Any]] = {}
        for row in self.state_store.list_event_mappings():
            self._index_mapping(
                row,
                by_sync=by_sync,
                by_source=by_source,
                by_user_uid=by_user_uid,
                by_stack_uid=by_stack_uid,
            )
        return by_sync, by_source, by_user_uid, by_stack_uid

    def _ensure_mapping(
        self,
        *,
        source: str,
        source_calendar_id: str,
        source_uid: str,
        preferred_user_uid: str,
        preferred_stack_uid: str,
        by_sync: dict[str, dict[str, Any]],
        by_source: dict[tuple[str, str, str], dict[str, Any]],
        by_user_uid: dict[str, dict[str, Any]],
        by_stack_uid: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        source_key = (str(source), str(source_calendar_id), str(source_uid))
        existing = by_source.get(source_key)
        if existing is not None:
            row = {
                "sync_id": str(existing["sync_id"]),
                "source": str(source),
                "source_calendar_id": str(source_calendar_id),
                "source_uid": str(source_uid),
                "source_href_hash": str(existing.get("source_href_hash", "")),
                "user_uid": str(existing.get("user_uid") or preferred_user_uid or self._stack_uid(str(existing["sync_id"]))),
                "stack_uid": str(existing.get("stack_uid") or preferred_stack_uid or self._stack_uid(str(existing["sync_id"]))),
                "status": str(existing.get("status", "active")),
            }
            self.state_store.upsert_event_mapping(**row)
            self._index_mapping(
                row,
                by_sync=by_sync,
                by_source=by_source,
                by_user_uid=by_user_uid,
                by_stack_uid=by_stack_uid,
            )
            return row

        sync_id = str(uuid4())
        row = {
            "sync_id": sync_id,
            "source": str(source),
            "source_calendar_id": str(source_calendar_id),
            "source_uid": str(source_uid),
            "source_href_hash": _hash_text(str(source_uid)),
            "user_uid": str(preferred_user_uid or self._stack_uid(sync_id)),
            "stack_uid": str(preferred_stack_uid or self._stack_uid(sync_id)),
            "status": "active",
        }
        self.state_store.upsert_event_mapping(**row)
        self._index_mapping(
            row,
            by_sync=by_sync,
            by_source=by_source,
            by_user_uid=by_user_uid,
            by_stack_uid=by_stack_uid,
        )
        return row

    @staticmethod
    def _source_label(mapping: dict[str, Any]) -> str:
        source = str(mapping.get("source", ""))
        if source == "ext":
            return f"ext:{mapping.get('source_calendar_id', '')}"
        return source or "user"

    def _stack_event_from_source(
        self,
        *,
        source_event: EventRecord,
        mapping: dict[str, Any],
        stack_calendar_id: str,
    ) -> EventRecord:
        return source_event.clone().with_updates(
            calendar_id=stack_calendar_id,
            uid=str(mapping["stack_uid"]),
            href="",
            source="stack",
            x_sync_id=str(mapping["sync_id"]),
            x_source=self._source_label(mapping),
            x_source_uid=str(mapping["source_uid"]),
            original_calendar_id=str(mapping["source_calendar_id"]),
            original_uid=str(mapping["source_uid"]),
        )

    @staticmethod
    def _merge_user_event_into_stack(target: EventRecord, user_event: EventRecord) -> EventRecord:
        merged = target.clone()
        merged.summary = user_event.summary
        merged.description = user_event.description
        merged.location = user_event.location
        merged.start = user_event.start
        merged.end = user_event.end
        merged.locked = bool(user_event.locked)
        return merged
