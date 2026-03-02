from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone


def _ensure_tz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def parse_iso_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_tz(value)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return _ensure_tz(parsed)


def serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_tz(value).isoformat()


def date_to_datetime(value: datetime | date | None, is_end: bool = False) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_tz(value)
    if is_end:
        return datetime.combine(value, time.max, tzinfo=timezone.utc)
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def planning_window(now: datetime, window_days: int) -> tuple[datetime, datetime]:
    now_utc = _ensure_tz(now)
    start = datetime.combine(now_utc.date(), time.min, tzinfo=now_utc.tzinfo)
    end_date = start.date() + timedelta(days=max(1, window_days) - 1)
    end = datetime.combine(end_date, time.max, tzinfo=now_utc.tzinfo)
    return start, end
