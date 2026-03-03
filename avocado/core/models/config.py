from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from avocado.core.models.constants import DEFAULT_AI_SYSTEM_PROMPT, DEFAULT_EDITABLE_FIELDS


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
    high_load_model: str = ""
    high_load_event_threshold: int = 0
    timeout_seconds: int = 90
    enabled: bool = True
    system_prompt: str = DEFAULT_AI_SYSTEM_PROMPT
    payload_logging_enabled: bool = False
    payload_log_path: str = "data/test_logs/ai_payload_exchange.jsonl"
    payload_log_max_chars: int = 200000

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AIConfig":
        data = data or {}
        return cls(
            base_url=str(data.get("base_url", "https://api.openai.com/v1")).strip()
            or "https://api.openai.com/v1",
            api_key=str(data.get("api_key", "")).strip(),
            model=str(data.get("model", "gpt-4o-mini")).strip() or "gpt-4o-mini",
            high_load_model=str(data.get("high_load_model", "")).strip(),
            high_load_event_threshold=max(0, int(data.get("high_load_event_threshold", 0))),
            timeout_seconds=int(data.get("timeout_seconds", 90)),
            enabled=bool(data.get("enabled", True)),
            system_prompt=str(data.get("system_prompt", DEFAULT_AI_SYSTEM_PROMPT)).strip()
            or DEFAULT_AI_SYSTEM_PROMPT,
            payload_logging_enabled=bool(data.get("payload_logging_enabled", False)),
            payload_log_path=str(
                data.get("payload_log_path", "data/test_logs/ai_payload_exchange.jsonl")
            ).strip()
            or "data/test_logs/ai_payload_exchange.jsonl",
            payload_log_max_chars=max(1000, int(data.get("payload_log_max_chars", 200000))),
        )


@dataclass
class SyncConfig:
    window_days: int = 7
    interval_seconds: int = 300
    timezone: str = "UTC"
    timezone_source: str = "host"
    freeze_hours: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SyncConfig":
        data = data or {}
        timezone_source = str(data.get("timezone_source", "host")).strip().lower() or "host"
        if timezone_source not in {"host", "manual"}:
            timezone_source = "host"
        return cls(
            window_days=max(1, int(data.get("window_days", 7))),
            interval_seconds=max(30, int(data.get("interval_seconds", 300))),
            timezone=str(data.get("timezone", "UTC")).strip() or "UTC",
            timezone_source=timezone_source,
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
    locked_calendar_ids: list[str] = field(default_factory=list)

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
        locked_calendar_ids: list[str] = []
        for item in data.get("locked_calendar_ids", []) or []:
            calendar_id = str(item or "").strip()
            if not calendar_id:
                continue
            if calendar_id not in locked_calendar_ids:
                locked_calendar_ids.append(calendar_id)
        return cls(
            stack_calendar_id=stack_calendar_id,
            stack_calendar_name=stack_calendar_name,
            user_calendar_id=str(data.get("user_calendar_id", "")).strip(),
            user_calendar_name=user_calendar_name,
            new_calendar_id=new_calendar_id,
            new_calendar_name=new_calendar_name,
            locked_calendar_ids=locked_calendar_ids,
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


def default_app_config() -> AppConfig:
    return AppConfig()
