from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from avocado.core.models import EventRecord
from avocado.integrations.caldav.codec import build_ical, extract_uid_from_raw_ical, parse_resource


class CalendarOpsMixin:
    def fetch_events(
        self,
        calendar_id: str,
        start: datetime,
        end: datetime,
    ) -> list[EventRecord]:
        self._connect()
        calendar = self._get_calendar(calendar_id)
        resources = calendar.date_search(start=start, end=end, expand=True)
        events: list[EventRecord] = []
        for item in resources:
            event = parse_resource(calendar_id, item)
            if event.uid:
                events.append(event)
        return events

    def upsert_event(
        self,
        calendar_id: str,
        event: EventRecord,
        *,
        expected_etag: str = "",
    ) -> EventRecord:
        self._connect()
        calendar = self._get_calendar(calendar_id)
        if expected_etag:
            latest = self.get_event_by_uid(calendar_id, event.uid)
            if latest is not None and latest.etag and latest.etag != expected_etag:
                raise RuntimeError("etag_conflict")
        raw_ical = build_ical(event)

        updated_resource = None
        if event.href:
            try:
                updated_resource = calendar.event_by_url(event.href)
                updated_resource.data = raw_ical
                updated_resource.save()
            except Exception:
                updated_resource = None

        if updated_resource is None:
            try:
                existing = self._find_resource_by_uid(calendar, event.uid)
                if existing is not None:
                    existing.data = raw_ical
                    existing.save()
                    updated_resource = existing
            except Exception:
                updated_resource = None

        if updated_resource is None:
            try:
                updated_resource = calendar.save_event(raw_ical)
            except Exception:
                try:
                    existing = self._find_resource_by_uid(calendar, event.uid)
                    if existing is None:
                        existing = self._find_resource_by_uid_in_range(
                            calendar,
                            event.uid,
                            event.start,
                            event.end,
                        )
                    if existing is not None:
                        existing.data = raw_ical
                        existing.save()
                        updated_resource = existing
                    else:
                        raise
                except Exception:
                    raise

        parsed = parse_resource(calendar_id, updated_resource)
        parsed.source = event.source
        parsed.locked = event.locked
        parsed.x_sync_id = event.x_sync_id
        parsed.x_source = event.x_source
        parsed.x_source_uid = event.x_source_uid
        parsed.original_calendar_id = event.original_calendar_id
        parsed.original_uid = event.original_uid
        return parsed

    def _find_resource_by_uid(self, calendar: Any, uid: str) -> Any:
        if not uid:
            return None
        try:
            resource = calendar.event_by_uid(uid)
            if isinstance(resource, list):
                resource = resource[0] if resource else None
            if resource is not None:
                return resource
        except Exception:
            pass

        try:
            for resource in calendar.events():
                candidate_uid = extract_uid_from_raw_ical(getattr(resource, "data", ""))
                if candidate_uid == uid:
                    return resource
        except Exception:
            pass
        return None

    def _find_resource_by_uid_in_range(
        self,
        calendar: Any,
        uid: str,
        start: datetime | None,
        end: datetime | None,
    ) -> Any:
        if not uid or start is None or end is None:
            return None
        try:
            begin = start - timedelta(days=7)
            finish = end + timedelta(days=7)
            for resource in calendar.date_search(start=begin, end=finish, expand=True):
                candidate_uid = extract_uid_from_raw_ical(getattr(resource, "data", ""))
                if candidate_uid == uid:
                    return resource
        except Exception:
            return None
        return None

    def delete_event(self, calendar_id: str, uid: str = "", href: str = "") -> bool:
        self._connect()
        calendar = self._get_calendar(calendar_id)
        resource = None
        if href:
            try:
                resource = calendar.event_by_url(href)
            except Exception:
                resource = None
        if resource is None and uid:
            resource = self._find_resource_by_uid(calendar, uid)
        if resource is None:
            return False
        try:
            resource.delete()
            return True
        except Exception:
            return False

    def delete_event_with_etag(self, calendar_id: str, uid: str, expected_etag: str, href: str = "") -> bool:
        if expected_etag:
            existing = self.get_event_by_uid(calendar_id, uid)
            if existing is not None and existing.etag and existing.etag != expected_etag:
                raise RuntimeError("etag_conflict")
        return self.delete_event(calendar_id, uid=uid, href=href)

    def get_event_by_uid(self, calendar_id: str, uid: str) -> EventRecord | None:
        self._connect()
        calendar = self._get_calendar(calendar_id)
        resource = self._find_resource_by_uid(calendar, uid)
        if resource is None:
            return None
        return parse_resource(calendar_id, resource)
