from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any


DEFAULT_EDITABLE_FIELDS = ["start", "end", "summary", "location", "description"]


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


@dataclass
class CalDAVConfig:
    base_url: str = ""
    username: str = ""
    password: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CalDAVConfig":
        data = data or {}
        return cls(
            base_url=str(data.get("base_url", "")).strip(),
            username=str(data.get("username", "")).strip(),
            password=str(data.get("password", "")).strip(),
        )


@dataclass
class AIConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_seconds: int = 90

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AIConfig":
        data = data or {}
        return cls(
            base_url=str(data.get("base_url", "")).strip(),
            api_key=str(data.get("api_key", "")).strip(),
            model=str(data.get("model", "gpt-4o-mini")).strip() or "gpt-4o-mini",
            timeout_seconds=int(data.get("timeout_seconds", 90)),
        )


@dataclass
class SyncConfig:
    window_days: int = 7
    interval_seconds: int = 300
    timezone: str = "UTC"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SyncConfig":
        data = data or {}
        return cls(
            window_days=max(1, int(data.get("window_days", 7))),
            interval_seconds=max(30, int(data.get("interval_seconds", 300))),
            timezone=str(data.get("timezone", "UTC")).strip() or "UTC",
        )


@dataclass
class CalendarRulesConfig:
    immutable_keywords: list[str] = field(default_factory=lambda: ["work", "固定", "fixed"])
    immutable_calendar_ids: list[str] = field(default_factory=list)
    staging_calendar_id: str = ""
    staging_calendar_name: str = "Avocado AI Staging"
    per_calendar_defaults: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CalendarRulesConfig":
        data = data or {}
        raw_defaults = data.get("per_calendar_defaults", {})
        normalized_defaults: dict[str, dict[str, Any]] = {}
        if isinstance(raw_defaults, dict):
            for key, value in raw_defaults.items():
                calendar_id = str(key).strip()
                if not calendar_id or not isinstance(value, dict):
                    continue
                mode = str(value.get("mode", "editable")).strip().lower()
                if mode not in {"editable", "immutable"}:
                    mode = "editable"
                normalized_defaults[calendar_id] = {
                    "mode": mode,
                    "locked": bool(value.get("locked", False)),
                    "mandatory": bool(value.get("mandatory", False)),
                }
        return cls(
            immutable_keywords=[str(x).strip() for x in data.get("immutable_keywords", []) if str(x).strip()],
            immutable_calendar_ids=[
                str(x).strip() for x in data.get("immutable_calendar_ids", []) if str(x).strip()
            ],
            staging_calendar_id=str(data.get("staging_calendar_id", "")).strip(),
            staging_calendar_name=str(data.get("staging_calendar_name", "Avocado AI Staging")).strip()
            or "Avocado AI Staging",
            per_calendar_defaults=normalized_defaults,
        )


@dataclass
class TaskDefaultsConfig:
    locked: bool = False
    mandatory: bool = False
    editable_fields: list[str] = field(default_factory=lambda: list(DEFAULT_EDITABLE_FIELDS))

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TaskDefaultsConfig":
        data = data or {}
        editable_fields = data.get("editable_fields", DEFAULT_EDITABLE_FIELDS)
        cleaned = [str(x).strip() for x in editable_fields if str(x).strip()]
        return cls(
            locked=bool(data.get("locked", False)),
            mandatory=bool(data.get("mandatory", False)),
            editable_fields=cleaned or list(DEFAULT_EDITABLE_FIELDS),
        )


@dataclass
class AppConfig:
    caldav: CalDAVConfig = field(default_factory=CalDAVConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    calendar_rules: CalendarRulesConfig = field(default_factory=CalendarRulesConfig)
    task_defaults: TaskDefaultsConfig = field(default_factory=TaskDefaultsConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AppConfig":
        data = data or {}
        return cls(
            caldav=CalDAVConfig.from_dict(data.get("caldav")),
            ai=AIConfig.from_dict(data.get("ai")),
            sync=SyncConfig.from_dict(data.get("sync")),
            calendar_rules=CalendarRulesConfig.from_dict(data.get("calendar_rules")),
            task_defaults=TaskDefaultsConfig.from_dict(data.get("task_defaults")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalendarInfo:
    calendar_id: str
    name: str
    url: str
    immutable_suggested: bool = False

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
    mandatory: bool = False
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
            mandatory=self.mandatory,
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


def default_app_config() -> AppConfig:
    return AppConfig()


def planning_window(now: datetime, window_days: int) -> tuple[datetime, datetime]:
    now_utc = _ensure_tz(now)
    start = datetime.combine(now_utc.date(), time.min, tzinfo=now_utc.tzinfo)
    end_date = start.date() + timedelta(days=max(1, window_days) - 1)
    end = datetime.combine(end_date, time.max, tzinfo=now_utc.tzinfo)
    return start, end
