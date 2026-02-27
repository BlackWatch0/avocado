from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from avocado.ai_client import OpenAICompatibleClient
from avocado.caldav_client import CalDAVService
from avocado.config_manager import ConfigManager
from avocado.models import parse_iso_datetime
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
    user_calendar_id: str = ""
    user_calendar_name: str | None = None
    intake_calendar_id: str = ""
    intake_calendar_name: str | None = None
    per_calendar_defaults: dict[str, dict[str, Any]] = Field(default_factory=dict)


class CustomWindowSyncRequest(BaseModel):
    start: str
    end: str


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


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


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
            if config.caldav.base_url and config.caldav.username:
                stage_info = service.ensure_staging_calendar(
                    config.calendar_rules.staging_calendar_id,
                    config.calendar_rules.staging_calendar_name,
                )
                user_info = service.ensure_staging_calendar(
                    config.calendar_rules.user_calendar_id,
                    config.calendar_rules.user_calendar_name,
                )
                intake_info = service.ensure_staging_calendar(
                    config.calendar_rules.intake_calendar_id,
                    config.calendar_rules.intake_calendar_name,
                )
                updates: dict[str, Any] = {"calendar_rules": {}}
                if config.calendar_rules.staging_calendar_id != stage_info.calendar_id:
                    updates["calendar_rules"]["staging_calendar_id"] = stage_info.calendar_id
                if config.calendar_rules.user_calendar_id != user_info.calendar_id:
                    updates["calendar_rules"]["user_calendar_id"] = user_info.calendar_id
                if config.calendar_rules.intake_calendar_id != intake_info.calendar_id:
                    updates["calendar_rules"]["intake_calendar_id"] = intake_info.calendar_id
                if updates["calendar_rules"]:
                    app.state.context.config_manager.update(updates)
                    config = app.state.context.config_manager.load()
            calendars = service.list_calendars()
            suggested = service.suggest_immutable_calendar_ids(
                calendars, config.calendar_rules.immutable_keywords
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        output = []
        stage_name_key = _normalize_name(config.calendar_rules.staging_calendar_name)
        user_name_key = _normalize_name(config.calendar_rules.user_calendar_name)
        intake_name_key = _normalize_name(config.calendar_rules.intake_calendar_name)
        per_calendar_defaults = config.calendar_rules.per_calendar_defaults
        immutable_explicit = set(config.calendar_rules.immutable_calendar_ids)
        editable_override = {
            cid
            for cid, behavior_entry in per_calendar_defaults.items()
            if str(behavior_entry.get("mode", "editable")).lower() == "editable"
        }
        for cal in calendars:
            item = cal.to_dict()
            behavior = per_calendar_defaults.get(cal.calendar_id, {})
            mode = str(behavior.get("mode", "editable")).lower()
            if mode not in {"editable", "immutable"}:
                mode = "editable"

            immutable_selected = cal.calendar_id in immutable_explicit or mode == "immutable"
            if mode == "editable":
                immutable_selected = cal.calendar_id in immutable_explicit and cal.calendar_id not in editable_override

            item["immutable_suggested"] = cal.calendar_id in suggested
            item["immutable_selected"] = immutable_selected
            item["is_staging"] = cal.calendar_id == config.calendar_rules.staging_calendar_id
            item["is_user"] = cal.calendar_id == config.calendar_rules.user_calendar_id
            item["is_intake"] = cal.calendar_id == config.calendar_rules.intake_calendar_id
            name_key = _normalize_name(cal.name)
            item["managed_duplicate"] = False
            item["managed_duplicate_role"] = ""
            if not item["is_staging"] and not item["is_user"] and not item["is_intake"]:
                if stage_name_key and name_key == stage_name_key:
                    item["managed_duplicate"] = True
                    item["managed_duplicate_role"] = "staging"
                elif user_name_key and name_key == user_name_key:
                    item["managed_duplicate"] = True
                    item["managed_duplicate_role"] = "user"
                elif intake_name_key and name_key == intake_name_key:
                    item["managed_duplicate"] = True
                    item["managed_duplicate_role"] = "intake"
            item["default_locked"] = bool(behavior.get("locked", config.task_defaults.locked))
            item["default_mandatory"] = bool(behavior.get("mandatory", config.task_defaults.mandatory))
            item["mode"] = "immutable" if immutable_selected else "editable"
            output.append(item)
        return {"calendars": output}

    @app.put("/api/calendar-rules")
    def put_calendar_rules(request: CalendarRulesUpdateRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "calendar_rules": {
                "immutable_keywords": request.immutable_keywords,
                "immutable_calendar_ids": request.immutable_calendar_ids,
                "staging_calendar_id": request.staging_calendar_id,
                "user_calendar_id": request.user_calendar_id,
                "intake_calendar_id": request.intake_calendar_id,
                "per_calendar_defaults": request.per_calendar_defaults,
            }
        }
        if request.staging_calendar_name is not None:
            payload["calendar_rules"]["staging_calendar_name"] = request.staging_calendar_name
        if request.user_calendar_name is not None:
            payload["calendar_rules"]["user_calendar_name"] = request.user_calendar_name
        if request.intake_calendar_name is not None:
            payload["calendar_rules"]["intake_calendar_name"] = request.intake_calendar_name
        updated = app.state.context.config_manager.update(payload)
        return {"message": "calendar rules updated", "calendar_rules": updated.calendar_rules.__dict__}

    @app.post("/api/sync/run")
    def trigger_sync() -> dict[str, str]:
        app.state.context.scheduler.trigger_manual()
        return {"message": "sync triggered"}

    @app.post("/api/sync/run-window")
    def trigger_sync_with_custom_window(request: CustomWindowSyncRequest) -> dict[str, Any]:
        start = parse_iso_datetime(request.start)
        end = parse_iso_datetime(request.end)
        if start is None or end is None:
            raise HTTPException(status_code=400, detail="Invalid start/end datetime")
        if end < start:
            raise HTTPException(status_code=400, detail="end must be later than start")
        result = app.state.context.sync_engine.run_once(
            trigger="manual-window",
            window_start_override=start,
            window_end_override=end,
        )
        return {
            "message": "sync completed",
            "result": result.to_dict(),
        }

    @app.post("/api/ai/test")
    def test_ai_connectivity() -> dict[str, Any]:
        config = app.state.context.config_manager.load()
        client = OpenAICompatibleClient(config.ai)
        ok, message = client.test_connectivity()
        return {"ok": ok, "message": message}

    @app.get("/api/sync/status")
    def sync_status(limit: int = 20) -> dict[str, Any]:
        return {"runs": app.state.context.state_store.recent_sync_runs(limit=limit)}

    @app.get("/api/audit/events")
    def audit_events(limit: int = 100) -> dict[str, Any]:
        return {"events": app.state.context.state_store.recent_audit_events(limit=limit)}

    return app


app = create_app()
