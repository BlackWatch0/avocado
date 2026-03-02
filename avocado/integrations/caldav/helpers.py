from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from typing import Any

from avocado.core.models import date_to_datetime

try:
    import caldav
except ImportError:  # pragma: no cover - dependency managed by requirements
    caldav = None

X_AVO_SYNC_ID = "X-AVO-SYNC-ID"
X_AVO_SOURCE = "X-AVO-SOURCE"
X_AVO_SOURCE_UID = "X-AVO-SOURCE-UID"


def data_hash(raw_ical: str) -> str:
    return hashlib.sha1(raw_ical.encode("utf-8")).hexdigest()  # nosec B324


def normalize_calendar_id(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def normalize_calendar_name(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", str(value or "").strip())
    return collapsed.casefold()


def coerce_datetime(value: Any, is_end: bool = False) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, date):
        return date_to_datetime(value, is_end=is_end)
    return None
