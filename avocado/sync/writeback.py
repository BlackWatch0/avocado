from __future__ import annotations

from datetime import datetime, timedelta, timezone

from avocado.core.models import EventRecord
from avocado.integrations.caldav import CalDAVService
from avocado.sync.helpers_identity import _event_fingerprint


class WritebackMixin:
    @staticmethod
    def _events_equal(current: EventRecord, desired: EventRecord) -> bool:
        return _event_fingerprint(current) == _event_fingerprint(desired)

    def _apply_upsert_with_retry(
        self,
        *,
        caldav_service: CalDAVService,
        calendar_id: str,
        desired_event: EventRecord,
        current_event: EventRecord | None,
    ) -> tuple[bool, EventRecord | None]:
        expected_etag = current_event.etag if current_event is not None else ""
        try:
            saved = caldav_service.upsert_event(
                calendar_id,
                desired_event,
                expected_etag=expected_etag,
            )
            return True, saved
        except RuntimeError as exc:
            if "etag_conflict" not in str(exc):
                return False, None

        latest = caldav_service.get_event_by_uid(calendar_id, desired_event.uid)
        if latest is None:
            try:
                saved = caldav_service.upsert_event(calendar_id, desired_event)
                return True, saved
            except Exception:
                return False, None
        retry_event = latest.with_updates(
            summary=desired_event.summary,
            description=desired_event.description,
            location=desired_event.location,
            start=desired_event.start,
            end=desired_event.end,
            locked=desired_event.locked,
            x_sync_id=desired_event.x_sync_id,
            x_source=desired_event.x_source,
            x_source_uid=desired_event.x_source_uid,
            original_calendar_id=desired_event.original_calendar_id,
            original_uid=desired_event.original_uid,
        )
        try:
            saved = caldav_service.upsert_event(
                calendar_id,
                retry_event,
                expected_etag=latest.etag,
            )
            return True, saved
        except Exception:
            return False, None

    def _apply_delete_with_retry(
        self,
        *,
        caldav_service: CalDAVService,
        calendar_id: str,
        uid: str,
        href: str,
        expected_etag: str,
    ) -> bool:
        try:
            return bool(
                caldav_service.delete_event_with_etag(
                    calendar_id,
                    uid=uid,
                    expected_etag=expected_etag,
                    href=href,
                )
            )
        except RuntimeError as exc:
            if "etag_conflict" not in str(exc):
                return False
        latest = caldav_service.get_event_by_uid(calendar_id, uid)
        if latest is None:
            return True
        try:
            return bool(
                caldav_service.delete_event_with_etag(
                    calendar_id,
                    uid=uid,
                    expected_etag=latest.etag,
                    href=latest.href,
                )
            )
        except Exception:
            return False

    def _clear_stack_for_migration(
        self,
        *,
        caldav_service: CalDAVService,
        stack_calendar_id: str,
        trigger: str,
        run_id: int,
    ) -> None:
        now = datetime.now(timezone.utc)
        events = caldav_service.fetch_events(
            stack_calendar_id,
            now - timedelta(days=3650),
            now + timedelta(days=3650),
        )
        deleted_events = 0
        for event in events:
            if not event.uid:
                continue
            if caldav_service.delete_event(stack_calendar_id, uid=event.uid, href=event.href):
                deleted_events += 1
        self.state_store.record_audit_event(
            calendar_id=stack_calendar_id,
            uid="calendar",
            action="stack_calendar_rebuilt",
            details={"trigger": trigger, "deleted_events": deleted_events},
            run_id=run_id,
        )


