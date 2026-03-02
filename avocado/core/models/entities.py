from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from avocado.core.models.time_utils import serialize_datetime


@dataclass
class CalendarInfo:
    calendar_id: str
    name: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EventRecord:
    calendar_id: str
    uid: str
    summary: str = ""
    description: str = ""
    location: str = ""
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    href: str = ""
    etag: str = ""
    source: str = "user"
    x_sync_id: str = ""
    x_source: str = ""
    x_source_uid: str = ""
    locked: bool = False
    original_calendar_id: str = ""
    original_uid: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start"] = serialize_datetime(self.start)
        payload["end"] = serialize_datetime(self.end)
        return payload

    def clone(self) -> "EventRecord":
        return EventRecord(
            calendar_id=self.calendar_id,
            uid=self.uid,
            summary=self.summary,
            description=self.description,
            location=self.location,
            start=self.start,
            end=self.end,
            all_day=self.all_day,
            href=self.href,
            etag=self.etag,
            source=self.source,
            x_sync_id=self.x_sync_id,
            x_source=self.x_source,
            x_source_uid=self.x_source_uid,
            locked=self.locked,
            original_calendar_id=self.original_calendar_id,
            original_uid=self.original_uid,
        )

    def with_updates(self, **kwargs: Any) -> "EventRecord":
        copied = self.clone()
        for key, value in kwargs.items():
            setattr(copied, key, value)
        return copied

    @property
    def window_key(self) -> str:
        return f"{self.calendar_id}:{self.uid}"


@dataclass
class SyncResult:
    status: str
    message: str
    duration_ms: int
    changes_applied: int
    conflicts: int
    trigger: str
    run_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "changes_applied": self.changes_applied,
            "conflicts": self.conflicts,
            "trigger": self.trigger,
            "run_at": serialize_datetime(self.run_at),
        }
