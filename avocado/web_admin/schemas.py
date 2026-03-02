from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConfigUpdateRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class CalendarRulesUpdateRequest(BaseModel):
    stack_calendar_id: str = ""
    stack_calendar_name: str | None = None
    user_calendar_id: str = ""
    user_calendar_name: str | None = None
    new_calendar_id: str = ""
    new_calendar_name: str | None = None
    locked_calendar_ids: list[str] = Field(default_factory=list)


class CustomWindowSyncRequest(BaseModel):
    start: str
    end: str


class AIChangeUndoRequest(BaseModel):
    audit_id: int


class AIChangeReviseRequest(BaseModel):
    audit_id: int
    instruction: str = Field(min_length=1, max_length=2000)
