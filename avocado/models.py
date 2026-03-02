from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any


DEFAULT_EDITABLE_FIELDS = ["start", "end", "summary", "location", "description"]
DEFAULT_AI_SYSTEM_PROMPT = """You are Avocado, an AI schedule planner.
You must respect constraints and only return JSON in this schema:
{
  "changes": [
    {
      "calendar_id": "string",
      "uid": "string",
      "start": "ISO8601 datetime",
      "end": "ISO8601 datetime",
      "summary": "string",
      "location": "string",
      "description": "string",
      "category": "string",
      "reason": "string"
    }
  ]
}

Rules:
1. Never modify events that are locked=true.
2. Only edit fields: start, end, summary, location, description.
3. Preserve user intent from [AI Task] block.
4. Keep output deterministic and concise.
"""


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
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_seconds: int = 90
    enabled: bool = True
    system_prompt: str = DEFAULT_AI_SYSTEM_PROMPT

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AIConfig":
        data = data or {}
        return cls(
            base_url=str(data.get("base_url", "https://api.openai.com/v1")).strip()
            or "https://api.openai.com/v1",
            api_key=str(data.get("api_key", "")).strip(),
            model=str(data.get("model", "gpt-4o-mini")).strip() or "gpt-4o-mini",
            timeout_seconds=int(data.get("timeout_seconds", 90)),
            enabled=bool(data.get("enabled", True)),
            system_prompt=str(data.get("system_prompt", DEFAULT_AI_SYSTEM_PROMPT)).strip()
            or DEFAULT_AI_SYSTEM_PROMPT,
        )


@dataclass
class SyncConfig:
    window_days: int = 7
    interval_seconds: int = 300
    timezone: str = "UTC"
    freeze_hours: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SyncConfig":
        data = data or {}
        return cls(
            window_days=max(1, int(data.get("window_days", 7))),
            interval_seconds=max(30, int(data.get("interval_seconds", 300))),
            timezone=str(data.get("timezone", "UTC")).strip() or "UTC",
            freeze_hours=max(0, int(data.get("freeze_hours", 0))),
        )


@dataclass
class CalendarRulesConfig:
    stack_calendar_id: str = ""
    stack_calendar_name: str = "Avocado Stack Calendar"
    user_calendar_id: str = ""
    user_calendar_name: str = "Avocado User Calendar"
    new_calendar_id: str = ""
    new_calendar_name: str = "Avocado New Calendar"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CalendarRulesConfig":
        data = data or {}
        stack_calendar_id = str(
            data.get("stack_calendar_id", data.get("staging_calendar_id", ""))
        ).strip()
        stack_calendar_name = str(
            data.get("stack_calendar_name", data.get("staging_calendar_name", "Avocado Stack Calendar"))
        ).strip()
        if not stack_calendar_name:
            stack_calendar_name = "Avocado Stack Calendar"
        user_calendar_name = str(data.get("user_calendar_name", "Avocado User Calendar")).strip()
        if not user_calendar_name:
            user_calendar_name = "Avocado User Calendar"
        new_calendar_id = str(
            data.get("new_calendar_id", data.get("intake_calendar_id", ""))
        ).strip()
        new_calendar_name = str(
            data.get("new_calendar_name", data.get("intake_calendar_name", "Avocado New Calendar"))
        ).strip()
        if not new_calendar_name:
            new_calendar_name = "Avocado New Calendar"
        return cls(
            stack_calendar_id=stack_calendar_id,
            stack_calendar_name=stack_calendar_name,
            user_calendar_id=str(data.get("user_calendar_id", "")).strip(),
            user_calendar_name=user_calendar_name,
            new_calendar_id=new_calendar_id,
            new_calendar_name=new_calendar_name,
        )


@dataclass
class TaskDefaultsConfig:
    locked: bool = False
    editable_fields: list[str] = field(default_factory=lambda: list(DEFAULT_EDITABLE_FIELDS))

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TaskDefaultsConfig":
        data = data or {}
        editable_fields = data.get("editable_fields", DEFAULT_EDITABLE_FIELDS)
        cleaned = [str(x).strip() for x in editable_fields if str(x).strip()]
        return cls(
            locked=bool(data.get("locked", False)),
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


def default_app_config() -> AppConfig:
    return AppConfig()


def planning_window(now: datetime, window_days: int) -> tuple[datetime, datetime]:
    now_utc = _ensure_tz(now)
    start = datetime.combine(now_utc.date(), time.min, tzinfo=now_utc.tzinfo)
    end_date = start.date() + timedelta(days=max(1, window_days) - 1)
    end = datetime.combine(end_date, time.max, tzinfo=now_utc.tzinfo)
    return start, end
