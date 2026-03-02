from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from icalendar import Calendar as ICalendar
from icalendar import Event as ICEvent

from avocado.core.models import EventRecord
from avocado.integrations.caldav.helpers import (
    X_AVO_SOURCE,
    X_AVO_SOURCE_UID,
    X_AVO_SYNC_ID,
    coerce_datetime,
    data_hash,
)


def first_vevent(calendar_obj: ICalendar) -> ICEvent | None:
    for component in calendar_obj.walk():
        if component.name == "VEVENT":
            return component
    return None


def decode_raw_ical(raw_data: Any) -> str:
    if isinstance(raw_data, bytes):
        return raw_data.decode("utf-8", errors="replace")
    return str(raw_data)


def extract_uid_from_raw_ical(raw_data: Any) -> str:
    try:
        raw_ical = decode_raw_ical(raw_data)
        calendar_obj = ICalendar.from_ical(raw_ical)
        vevent = first_vevent(calendar_obj)
        if vevent is None:
            return ""
        return str(vevent.get("UID", "")).strip()
    except Exception:
        return ""


def extract_etag(resource: Any, raw_ical: str) -> str:
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
    return data_hash(raw_ical)


def parse_resource(calendar_id: str, resource: Any) -> EventRecord:
    raw_data = resource.data
    raw_ical = decode_raw_ical(raw_data)

    calendar_obj = ICalendar.from_ical(raw_ical)
    vevent = first_vevent(calendar_obj)
    if vevent is None:
        raise RuntimeError("VEVENT missing in calendar resource.")

    uid = str(vevent.get("UID", "")).strip()
    summary = str(vevent.get("SUMMARY", "")).strip()
    description = str(vevent.get("DESCRIPTION", "")).strip()
    location = str(vevent.get("LOCATION", "")).strip()
    dtstart_raw = vevent.decoded("DTSTART") if vevent.get("DTSTART") is not None else None
    start = coerce_datetime(dtstart_raw, is_end=False)
    dtend_raw = vevent.decoded("DTEND") if vevent.get("DTEND") is not None else None
    end = coerce_datetime(dtend_raw, is_end=True)
    all_day = isinstance(dtstart_raw, date) and not isinstance(dtstart_raw, datetime)
    if start and end is None:
        end = start + timedelta(hours=1)
    href = str(getattr(resource, "url", "") or "")
    etag = data_hash(raw_ical)
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
        etag=extract_etag(resource, raw_ical) or etag,
        x_sync_id=x_sync_id,
        x_source=x_source,
        x_source_uid=x_source_uid,
    )


def build_ical(event: EventRecord) -> str:
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
