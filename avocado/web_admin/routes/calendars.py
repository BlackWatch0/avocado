from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, HTTPException

from avocado.integrations.caldav import CalDAVService
from avocado.web_admin.schemas import CalendarRulesUpdateRequest
from avocado.web_admin.utils import normalize_name

LOCK_NAME_PATTERN = re.compile(r"\[\s*l\s*\]", re.IGNORECASE)


def register_calendar_routes(app: FastAPI) -> None:
    @app.get("/api/calendars")
    def list_calendars() -> dict[str, Any]:
        config = app.state.context.config_manager.load()
        service = CalDAVService(config.caldav)
        try:
            calendars = service.list_calendars()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        output = []
        stack_name_key = normalize_name(config.calendar_rules.stack_calendar_name)
        user_name_key = normalize_name(config.calendar_rules.user_calendar_name)
        new_name_key = normalize_name(config.calendar_rules.new_calendar_name)
        for cal in calendars:
            item = cal.to_dict()
            item["is_stack"] = cal.calendar_id == config.calendar_rules.stack_calendar_id
            item["is_user"] = cal.calendar_id == config.calendar_rules.user_calendar_id
            item["is_new"] = cal.calendar_id == config.calendar_rules.new_calendar_id
            locked_by_name = bool(LOCK_NAME_PATTERN.search(str(cal.name or "")))
            item["source_locked"] = (
                cal.calendar_id in set(config.calendar_rules.locked_calendar_ids or []) or locked_by_name
            )
            name_key = normalize_name(cal.name)
            item["managed_duplicate"] = False
            item["managed_duplicate_role"] = ""
            if not item["is_stack"] and not item["is_user"] and not item["is_new"]:
                if stack_name_key and name_key == stack_name_key:
                    item["managed_duplicate"] = True
                    item["managed_duplicate_role"] = "stack"
                elif user_name_key and name_key == user_name_key:
                    item["managed_duplicate"] = True
                    item["managed_duplicate_role"] = "user"
                elif new_name_key and name_key == new_name_key:
                    item["managed_duplicate"] = True
                    item["managed_duplicate_role"] = "new"
            output.append(item)
        return {"calendars": output}

    @app.put("/api/calendar-rules")
    def put_calendar_rules(request: CalendarRulesUpdateRequest) -> dict[str, Any]:
        reserved = {
            request.stack_calendar_id,
            request.user_calendar_id,
            request.new_calendar_id,
        }
        locked_calendar_ids = []
        for item in request.locked_calendar_ids or []:
            value = str(item or "").strip()
            if not value or value in reserved or value in locked_calendar_ids:
                continue
            locked_calendar_ids.append(value)
        payload: dict[str, Any] = {
            "calendar_rules": {
                "stack_calendar_id": request.stack_calendar_id,
                "user_calendar_id": request.user_calendar_id,
                "new_calendar_id": request.new_calendar_id,
                "locked_calendar_ids": locked_calendar_ids,
            }
        }
        if request.stack_calendar_name is not None:
            payload["calendar_rules"]["stack_calendar_name"] = request.stack_calendar_name
        if request.user_calendar_name is not None:
            payload["calendar_rules"]["user_calendar_name"] = request.user_calendar_name
        if request.new_calendar_name is not None:
            payload["calendar_rules"]["new_calendar_name"] = request.new_calendar_name
        updated = app.state.context.config_manager.update(payload)
        return {"message": "calendar rules updated", "calendar_rules": updated.calendar_rules.__dict__}
