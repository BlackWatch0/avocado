from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from avocado.caldav_client import CalDAVService
from avocado.config_manager import ConfigManager
from avocado.scheduler import SyncScheduler
from avocado.state_store import StateStore
from avocado.sync_engine import SyncEngine


class ConfigUpdateRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class CalendarRulesUpdateRequest(BaseModel):
    immutable_keywords: list[str] = Field(default_factory=list)
    immutable_calendar_ids: list[str] = Field(default_factory=list)
    staging_calendar_id: str = ""
    staging_calendar_name: str | None = None


class AppContext:
    def __init__(self, config_path: str, state_path: str) -> None:
        self.config_manager = ConfigManager(config_path)
        self.state_store = StateStore(state_path)
        self.sync_engine = SyncEngine(self.config_manager, self.state_store)
        self.scheduler = SyncScheduler(self.sync_engine, self.config_manager)


def _masked_meta(config_dict: dict[str, Any]) -> dict[str, Any]:
    has_caldav_password = bool(config_dict.get("caldav", {}).get("password", "").strip())
    has_ai_api_key = bool(config_dict.get("ai", {}).get("api_key", "").strip())
    return {
        "caldav": {"password": {"is_masked": has_caldav_password}},
        "ai": {"api_key": {"is_masked": has_ai_api_key}},
    }


def _sanitize_config_payload(payload: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    current_caldav_password = str(current.get("caldav", {}).get("password", ""))
    current_ai_api_key = str(current.get("ai", {}).get("api_key", ""))

    caldav = sanitized.get("caldav")
    if isinstance(caldav, dict):
        password = caldav.get("password")
        if password is not None:
            password_text = str(password).strip()
            if password_text in {"", "***"}:
                if current_caldav_password:
                    caldav.pop("password", None)
                else:
                    caldav["password"] = ""
        if not caldav:
            sanitized.pop("caldav", None)

    ai = sanitized.get("ai")
    if isinstance(ai, dict):
        api_key = ai.get("api_key")
        if api_key is not None:
            api_key_text = str(api_key).strip()
            if api_key_text in {"", "***"}:
                if current_ai_api_key:
                    ai.pop("api_key", None)
                else:
                    ai["api_key"] = ""
        if not ai:
            sanitized.pop("ai", None)

    return sanitized


def create_app() -> FastAPI:
    config_path = os.getenv("AVOCADO_CONFIG_PATH", "config.yaml")
    state_path = os.getenv("AVOCADO_STATE_PATH", "data/state.db")
    context = AppContext(config_path=config_path, state_path=state_path)
    module_dir = Path(__file__).resolve().parent

    app = FastAPI(title="Avocado Admin", version="0.1.0")
    app.state.context = context
    app.mount("/static", StaticFiles(directory=str(module_dir / "static")), name="static")

    @app.on_event("startup")
    def _startup() -> None:
        app.state.context.scheduler.start()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        app.state.context.scheduler.stop()

    @app.get("/", include_in_schema=False)
    def admin_page() -> FileResponse:
        return FileResponse(module_dir / "templates" / "admin.html")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        return app.state.context.config_manager.masked()

    @app.put("/api/config")
    def put_config(request: ConfigUpdateRequest) -> dict[str, Any]:
        if not isinstance(request.payload, dict):
            raise HTTPException(status_code=400, detail="payload must be an object")
        current = app.state.context.config_manager.load().to_dict()
        sanitized_payload = _sanitize_config_payload(request.payload, current)
        updated = app.state.context.config_manager.update(sanitized_payload)
        return {
            "message": "config updated",
            "config": updated.to_dict(),
        }

    @app.get("/api/config/raw")
    def get_config_raw() -> dict[str, Any]:
        raw = app.state.context.config_manager.load().to_dict()
        masked = app.state.context.config_manager.masked()
        return {"config": masked, "meta": _masked_meta(raw)}

    @app.get("/api/calendars")
    def list_calendars() -> dict[str, Any]:
        config = app.state.context.config_manager.load()
        service = CalDAVService(config.caldav)
        try:
            calendars = service.list_calendars()
            suggested = service.suggest_immutable_calendar_ids(
                calendars, config.calendar_rules.immutable_keywords
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        output = []
        for cal in calendars:
            item = cal.to_dict()
            item["immutable_suggested"] = cal.calendar_id in suggested
            item["immutable_selected"] = cal.calendar_id in set(config.calendar_rules.immutable_calendar_ids)
            item["is_staging"] = cal.calendar_id == config.calendar_rules.staging_calendar_id
            output.append(item)
        return {"calendars": output}

    @app.put("/api/calendar-rules")
    def put_calendar_rules(request: CalendarRulesUpdateRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "calendar_rules": {
                "immutable_keywords": request.immutable_keywords,
                "immutable_calendar_ids": request.immutable_calendar_ids,
                "staging_calendar_id": request.staging_calendar_id,
            }
        }
        if request.staging_calendar_name is not None:
            payload["calendar_rules"]["staging_calendar_name"] = request.staging_calendar_name
        updated = app.state.context.config_manager.update(payload)
        return {"message": "calendar rules updated", "calendar_rules": updated.calendar_rules.__dict__}

    @app.post("/api/sync/run")
    def trigger_sync() -> dict[str, str]:
        app.state.context.scheduler.trigger_manual()
        return {"message": "sync triggered"}

    @app.get("/api/sync/status")
    def sync_status(limit: int = 20) -> dict[str, Any]:
        return {"runs": app.state.context.state_store.recent_sync_runs(limit=limit)}

    @app.get("/api/audit/events")
    def audit_events(limit: int = 100) -> dict[str, Any]:
        return {"events": app.state.context.state_store.recent_audit_events(limit=limit)}

    return app


app = create_app()
