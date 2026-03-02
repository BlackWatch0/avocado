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

X_AVO_SYNC_ID = "X-AVO-SYNC-ID"
X_AVO_SOURCE = "X-AVO-SOURCE"
X_AVO_SOURCE_UID = "X-AVO-SOURCE-UID"


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


def _extract_etag(resource: Any, raw_ical: str) -> str:
    candidate = str(getattr(resource, "etag", "") or "").strip()
    if candidate:
        return candidate
    props = getattr(resource, "props", {}) or {}
    if isinstance(props, dict):
        for key in ("{DAV:}getetag", "getetag"):
            value = props.get(key)
            if value is not None:
                text = str(value).strip()
                if text:
                    return text
    return _data_hash(raw_ical)


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

    def _get_calendar(self, calendar_id: str) -> Any:
        if calendar_id in self._calendar_cache:
            return self._calendar_cache[calendar_id]
        for calendar in self._principal.calendars():
            cid = str(calendar.url)
            self._calendar_cache[cid] = calendar
        if calendar_id not in self._calendar_cache:
            raise RuntimeError(f"Calendar not found: {calendar_id}")
        return self._calendar_cache[calendar_id]

    def ensure_managed_calendar(self, calendar_id: str, calendar_name: str) -> CalendarInfo:
        self._connect()
        calendars = self.list_calendars()
        calendar_id_norm = _normalize_calendar_id(calendar_id)
        if calendar_id_norm:
            for info in calendars:
                if _normalize_calendar_id(info.calendar_id) == calendar_id_norm:
                    return info
        calendar_name_norm = _normalize_calendar_name(calendar_name)
        if calendar_name_norm:
            same_name = [
                info for info in calendars if _normalize_calendar_name(info.name) == calendar_name_norm
            ]
            if same_name:
                same_name.sort(key=lambda item: item.calendar_id)
                return same_name[0]

        calendar = self._principal.make_calendar(name=calendar_name)
        created_id = str(calendar.url)
        self._calendar_cache[created_id] = calendar

        refreshed = self.list_calendars()
        created_norm = _normalize_calendar_id(created_id)
        for info in refreshed:
            if _normalize_calendar_id(info.calendar_id) == created_norm:
                return info

        fallback_name_norm = _normalize_calendar_name(calendar_name)
        if fallback_name_norm:
            same_name = [
                info for info in refreshed if _normalize_calendar_name(info.name) == fallback_name_norm
            ]
            if same_name:
                same_name.sort(key=lambda item: item.calendar_id)
                return same_name[0]

        return CalendarInfo(
            calendar_id=created_id,
            name=getattr(calendar, "name", calendar_name) or calendar_name,
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
        x_sync_id = str(vevent.get(X_AVO_SYNC_ID, "")).strip()
        x_source = str(vevent.get(X_AVO_SOURCE, "")).strip()
        x_source_uid = str(vevent.get(X_AVO_SOURCE_UID, "")).strip()
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
            etag=_extract_etag(resource, raw_ical) or etag,
            x_sync_id=x_sync_id,
            x_source=x_source,
            x_source_uid=x_source_uid,
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
        if event.x_sync_id:
            vevent.add(X_AVO_SYNC_ID, event.x_sync_id)
        if event.x_source:
            vevent.add(X_AVO_SOURCE, event.x_source)
        if event.x_source_uid:
            vevent.add(X_AVO_SOURCE_UID, event.x_source_uid)
        if event.start is not None:
            vevent.add("DTSTART", event.start)
        if event.end is not None:
            vevent.add("DTEND", event.end)
        calendar_obj.add_component(vevent)
        return calendar_obj.to_ical().decode("utf-8")

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

        parsed = self._parse_resource(calendar_id, updated_resource)
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
                candidate_uid = _extract_uid_from_raw_ical(getattr(resource, "data", ""))
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
                candidate_uid = _extract_uid_from_raw_ical(getattr(resource, "data", ""))
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
        return self._parse_resource(calendar_id, resource)

    def list_window_index(self, calendar_id: str, start: datetime, end: datetime) -> list[dict[str, str]]:
        self._connect()
        calendar = self._get_calendar(calendar_id)
        resources = calendar.date_search(start=start, end=end, expand=True)
        output: list[dict[str, str]] = []
        for resource in resources:
            href = str(getattr(resource, "url", "") or "")
            raw_data = getattr(resource, "data", "")
            raw_ical = _decode_raw_ical(raw_data)
            uid = _extract_uid_from_raw_ical(raw_ical)
            etag = _extract_etag(resource, raw_ical)
            if not uid:
                continue
            output.append({"uid": uid, "href": href, "etag": etag})
        return output

    def fetch_changes_by_token(
        self, calendar_id: str, sync_token: str | None
    ) -> dict[str, Any]:
        self._connect()
        calendar = self._get_calendar(calendar_id)
        try:
            updates = calendar.objects_by_sync_token(sync_token=sync_token, load_objects=False)
        except Exception as exc:
            return {
                "supported": False,
                "add_update": [],
                "delete": [],
                "next_token": sync_token or "",
                "error": f"{type(exc).__name__}: {exc}",
            }

        next_token = str(getattr(updates, "sync_token", "") or sync_token or "")
        add_update: list[EventRecord] = []
        deleted: list[dict[str, str]] = []
        for obj in updates:
            href = str(getattr(obj, "url", "") or "")
            uid = ""
            raw_data = getattr(obj, "data", "")
            if raw_data:
                uid = _extract_uid_from_raw_ical(raw_data)
            try:
                obj.load()
                parsed = self._parse_resource(calendar_id, obj)
                if parsed.uid:
                    add_update.append(parsed)
                elif uid:
                    parsed.uid = uid
                    add_update.append(parsed)
            except Exception:
                deleted.append({"uid": uid, "href": href})
        return {
            "supported": True,
            "add_update": add_update,
            "delete": deleted,
            "next_token": next_token,
            "error": "",
        }
