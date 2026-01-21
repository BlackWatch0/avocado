from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    uid: str
    start: date | datetime
    end: date | datetime
    all_day: bool
    summary: str
    description: str
    location: Optional[str]
    rrule_raw: Optional[str]
    exdate_raw: Optional[list[str]]
    rdate_raw: Optional[list[str]]
    raw_ics: str
    href: Optional[str] = None
    etag: Optional[str] = None
    collection_url: Optional[str] = None


def parse_ics_events(ics_text: str) -> list[Event]:
    """Parse ICS text into a list of Event objects.

    When multiple VEVENT blocks are present, all of them are returned.
    """
    unfolded = _unfold_lines(ics_text)
    events: list[list[str]] = []
    current: list[str] = []
    in_event = False
    for line in unfolded:
        if line == "BEGIN:VEVENT":
            in_event = True
            current = []
            continue
        if line == "END:VEVENT":
            in_event = False
            events.append(current)
            current = []
            continue
        if in_event:
            current.append(line)

    parsed_events = []
    for lines in events:
        try:
            parsed_events.append(_parse_event(lines, ics_text))
        except Exception as exc:  # pragma: no cover - unexpected
            logger.error("Failed to parse event: %s", exc)
    return parsed_events


def _parse_event(lines: list[str], raw_ics: str) -> Event:
    data: dict[str, list[tuple[dict[str, str], str]]] = {}
    for line in lines:
        if ":" not in line:
            continue
        name_part, value = line.split(":", 1)
        name, params = _parse_params(name_part)
        data.setdefault(name, []).append((params, value))

    uid = _get_first_value(data, "UID") or ""
    summary = _get_first_value(data, "SUMMARY") or ""
    description = _unescape_text(_get_first_value(data, "DESCRIPTION") or "")
    location = _get_first_value(data, "LOCATION")

    start, start_all_day = _parse_datetime(data, "DTSTART")
    end, end_all_day = _parse_datetime(data, "DTEND")
    all_day = start_all_day or end_all_day

    rrule_raw = _get_first_value(data, "RRULE")
    exdate_raw = _get_values(data, "EXDATE")
    rdate_raw = _get_values(data, "RDATE")

    return Event(
        uid=uid,
        start=start,
        end=end,
        all_day=all_day,
        summary=summary,
        description=description,
        location=location,
        rrule_raw=rrule_raw,
        exdate_raw=exdate_raw,
        rdate_raw=rdate_raw,
        raw_ics=raw_ics,
    )


def _unfold_lines(ics_text: str) -> list[str]:
    lines = ics_text.splitlines()
    unfolded: list[str] = []
    for line in lines:
        if line.startswith(" ") or line.startswith("\t"):
            if unfolded:
                unfolded[-1] += line[1:]
            else:
                unfolded.append(line.lstrip())
        else:
            unfolded.append(line)
    return unfolded


def _parse_params(name_part: str) -> tuple[str, dict[str, str]]:
    parts = name_part.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            params[key.upper()] = value
    return name, params


def _parse_datetime(
    data: dict[str, list[tuple[dict[str, str], str]]], key: str
) -> tuple[date | datetime, bool]:
    entries = data.get(key, [])
    if not entries:
        return datetime.min, False
    params, value = entries[0]
    value = value.strip()
    if params.get("VALUE", "").upper() == "DATE":
        return datetime.strptime(value, "%Y%m%d").date(), True
    if value.endswith("Z"):
        dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ")
        return dt.replace(tzinfo=ZoneInfo("UTC")), False
    tzid = params.get("TZID")
    if tzid:
        dt = datetime.strptime(value, "%Y%m%dT%H%M%S")
        return dt.replace(tzinfo=ZoneInfo(tzid)), False
    return datetime.strptime(value, "%Y%m%dT%H%M%S"), False


def _get_first_value(data: dict[str, list[tuple[dict[str, str], str]]], key: str) -> Optional[str]:
    entries = data.get(key, [])
    if not entries:
        return None
    return entries[0][1]


def _get_values(data: dict[str, list[tuple[dict[str, str], str]]], key: str) -> Optional[list[str]]:
    entries = data.get(key, [])
    if not entries:
        return None
    return [value for _, value in entries]


def _unescape_text(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )
