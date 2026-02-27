from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from icalendar import Calendar as ICalendar
from icalendar import Event as ICEvent

from avocado.models import CalendarInfo, CalDAVConfig, EventRecord, date_to_datetime

try:
    import caldav
except ImportError:  # pragma: no cover - dependency managed by requirements
    caldav = None


def _data_hash(raw_ical: str) -> str:
    return hashlib.sha1(raw_ical.encode("utf-8")).hexdigest()  # nosec B324


def _normalize_calendar_id(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _normalize_calendar_name(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", str(value or "").strip())
    return collapsed.casefold()


def _coerce_datetime(value: Any, is_end: bool = False) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, date):
        return date_to_datetime(value, is_end=is_end)
    return None


def _first_vevent(calendar_obj: ICalendar) -> ICEvent | None:
    for component in calendar_obj.walk():
        if component.name == "VEVENT":
            return component
    return None


def _decode_raw_ical(raw_data: Any) -> str:
    if isinstance(raw_data, bytes):
        return raw_data.decode("utf-8", errors="replace")
    return str(raw_data)


def _extract_uid_from_raw_ical(raw_data: Any) -> str:
    try:
        raw_ical = _decode_raw_ical(raw_data)
        calendar_obj = ICalendar.from_ical(raw_ical)
        vevent = _first_vevent(calendar_obj)
        if vevent is None:
            return ""
        return str(vevent.get("UID", "")).strip()
    except Exception:
        return ""


class CalDAVService:
    def __init__(self, config: CalDAVConfig) -> None:
        self.config = config
        self._client: Any = None
        self._principal: Any = None
        self._calendar_cache: dict[str, Any] = {}

    def _require_dependency(self) -> None:
        if caldav is None:
            raise RuntimeError("caldav dependency is not installed.")

    def _connect(self) -> None:
        self._require_dependency()
        if self._principal is not None:
            return
        if not self.config.base_url or not self.config.username:
            raise RuntimeError("CalDAV config is incomplete.")
        self._client = caldav.DAVClient(
            url=self.config.base_url,
            username=self.config.username,
            password=self.config.password,
        )
        self._principal = self._client.principal()

    def list_calendars(self) -> list[CalendarInfo]:
        self._connect()
        self._calendar_cache = {}
        calendars: list[CalendarInfo] = []
        for calendar in self._principal.calendars():
            calendar_id = str(calendar.url)
            name = getattr(calendar, "name", "") or calendar_id
            self._calendar_cache[calendar_id] = calendar
            calendars.append(CalendarInfo(calendar_id=calendar_id, name=name, url=calendar_id))
        return calendars

    @staticmethod
    def suggest_immutable_calendar_ids(
        calendars: list[CalendarInfo], keywords: list[str]
    ) -> set[str]:
        normalized_keywords = [x.strip().lower() for x in keywords if x.strip()]
        if not normalized_keywords:
            return set()
        suggested: set[str] = set()
        for cal in calendars:
            name_lower = cal.name.lower()
            if any(keyword in name_lower for keyword in normalized_keywords):
                suggested.add(cal.calendar_id)
        return suggested

    def _get_calendar(self, calendar_id: str) -> Any:
        if calendar_id in self._calendar_cache:
            return self._calendar_cache[calendar_id]
        for calendar in self._principal.calendars():
            cid = str(calendar.url)
            self._calendar_cache[cid] = calendar
        if calendar_id not in self._calendar_cache:
            raise RuntimeError(f"Calendar not found: {calendar_id}")
        return self._calendar_cache[calendar_id]

    def ensure_staging_calendar(self, staging_id: str, staging_name: str) -> CalendarInfo:
        self._connect()
        calendars = self.list_calendars()
        staging_id_norm = _normalize_calendar_id(staging_id)
        if staging_id_norm:
            for info in calendars:
                if _normalize_calendar_id(info.calendar_id) == staging_id_norm:
                    return info
        staging_name_norm = _normalize_calendar_name(staging_name)
        if staging_name_norm:
            same_name = [
                info for info in calendars if _normalize_calendar_name(info.name) == staging_name_norm
            ]
            if same_name:
                same_name.sort(key=lambda item: item.calendar_id)
                return same_name[0]

        calendar = self._principal.make_calendar(name=staging_name)
        created_id = str(calendar.url)
        self._calendar_cache[created_id] = calendar

        refreshed = self.list_calendars()
        created_norm = _normalize_calendar_id(created_id)
        for info in refreshed:
            if _normalize_calendar_id(info.calendar_id) == created_norm:
                return info

        fallback_name_norm = _normalize_calendar_name(staging_name)
        if fallback_name_norm:
            same_name = [
                info for info in refreshed if _normalize_calendar_name(info.name) == fallback_name_norm
            ]
            if same_name:
                same_name.sort(key=lambda item: item.calendar_id)
                return same_name[0]

        return CalendarInfo(
            calendar_id=created_id,
            name=getattr(calendar, "name", staging_name) or staging_name,
            url=created_id,
        )

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
            event = self._parse_resource(calendar_id, item)
            if event.uid:
                events.append(event)
        return events

    def _parse_resource(self, calendar_id: str, resource: Any) -> EventRecord:
        raw_data = resource.data
        raw_ical = _decode_raw_ical(raw_data)

        calendar_obj = ICalendar.from_ical(raw_ical)
        vevent = _first_vevent(calendar_obj)
        if vevent is None:
            raise RuntimeError("VEVENT missing in calendar resource.")

        uid = str(vevent.get("UID", "")).strip()
        summary = str(vevent.get("SUMMARY", "")).strip()
        description = str(vevent.get("DESCRIPTION", "")).strip()
        location = str(vevent.get("LOCATION", "")).strip()
        dtstart_raw = vevent.decoded("DTSTART") if vevent.get("DTSTART") is not None else None
        start = _coerce_datetime(dtstart_raw, is_end=False)
        dtend_raw = vevent.decoded("DTEND") if vevent.get("DTEND") is not None else None
        end = _coerce_datetime(dtend_raw, is_end=True)
        all_day = isinstance(dtstart_raw, date) and not isinstance(dtstart_raw, datetime)
        if start and end is None:
            end = start + timedelta(hours=1)
        href = str(getattr(resource, "url", "") or "")
        etag = _data_hash(raw_ical)
        return EventRecord(
            calendar_id=calendar_id,
            uid=uid,
            summary=summary,
            description=description,
            location=location,
            start=start,
            end=end,
            all_day=all_day,
            href=href,
            etag=etag,
        )

    def _build_ical(self, event: EventRecord) -> str:
        calendar_obj = ICalendar()
        calendar_obj.add("PRODID", "-//Avocado//Calendar Sync//EN")
        calendar_obj.add("VERSION", "2.0")
        vevent = ICEvent()
        vevent.add("UID", event.uid)
        vevent.add("SUMMARY", event.summary or "")
        vevent.add("DESCRIPTION", event.description or "")
        if event.location:
            vevent.add("LOCATION", event.location)
        if event.start is not None:
            vevent.add("DTSTART", event.start)
        if event.end is not None:
            vevent.add("DTEND", event.end)
        calendar_obj.add_component(vevent)
        return calendar_obj.to_ical().decode("utf-8")

    def upsert_event(self, calendar_id: str, event: EventRecord) -> EventRecord:
        self._connect()
        calendar = self._get_calendar(calendar_id)
        raw_ical = self._build_ical(event)

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
                # Some CalDAV backends may race on UID uniqueness checks.
                try:
                    existing = self._find_resource_by_uid(calendar, event.uid)
                    if existing is not None:
                        existing.data = raw_ical
                        existing.save()
                        updated_resource = existing
                    else:
                        raise
                except Exception:
                    raise

        parsed = self._parse_resource(calendar_id, updated_resource)
        parsed.source = event.source
        parsed.mandatory = event.mandatory
        parsed.locked = event.locked
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
                candidate_uid = _extract_uid_from_raw_ical(getattr(resource, "data", ""))
                if candidate_uid == uid:
                    return resource
        except Exception:
            pass
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

    def get_event_by_uid(self, calendar_id: str, uid: str) -> EventRecord | None:
        self._connect()
        calendar = self._get_calendar(calendar_id)
        resource = self._find_resource_by_uid(calendar, uid)
        if resource is None:
            return None
        return self._parse_resource(calendar_id, resource)
