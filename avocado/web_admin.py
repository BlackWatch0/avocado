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
from avocado.models import EventRecord, parse_iso_datetime
from avocado.scheduler import SyncScheduler
from avocado.state_store import StateStore
from avocado.sync_engine import SyncEngine
from avocado.task_block import set_ai_task_user_intent


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


class AIChangeUndoRequest(BaseModel):
    audit_id: int


class AIChangeReviseRequest(BaseModel):
    audit_id: int
    instruction: str = Field(min_length=1, max_length=2000)


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


def _event_from_dict(payload: dict[str, Any]) -> EventRecord:
    return EventRecord(
        calendar_id=str(payload.get("calendar_id", "")).strip(),
        uid=str(payload.get("uid", "")).strip(),
        summary=str(payload.get("summary", "")).strip(),
        description=str(payload.get("description", "") or ""),
        location=str(payload.get("location", "") or ""),
        start=parse_iso_datetime(payload.get("start")),
        end=parse_iso_datetime(payload.get("end")),
        all_day=bool(payload.get("all_day", False)),
        href=str(payload.get("href", "") or ""),
        etag=str(payload.get("etag", "") or ""),
        source=str(payload.get("source", "user") or "user"),
        mandatory=bool(payload.get("mandatory", False)),
        locked=bool(payload.get("locked", False)),
        original_calendar_id=str(payload.get("original_calendar_id", "") or ""),
        original_uid=str(payload.get("original_uid", "") or ""),
    )


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
            item["default_mandatory"] = False
            item["mode"] = "immutable" if immutable_selected else "editable"
            output.append(item)
        return {"calendars": output}

    @app.put("/api/calendar-rules")
    def put_calendar_rules(request: CalendarRulesUpdateRequest) -> dict[str, Any]:
        current_config = app.state.context.config_manager.load()
        reserved_calendar_ids = {
            current_config.calendar_rules.staging_calendar_id,
            current_config.calendar_rules.user_calendar_id,
            current_config.calendar_rules.intake_calendar_id,
        }
        reserved_calendar_ids = {cid for cid in reserved_calendar_ids if str(cid).strip()}

        filtered_defaults: dict[str, dict[str, Any]] = {}
        for calendar_id, behavior in (request.per_calendar_defaults or {}).items():
            cid = str(calendar_id).strip()
            if not cid or cid in reserved_calendar_ids:
                continue
            entry = behavior or {}
            mode = str(entry.get("mode", "editable")).strip().lower()
            if mode not in {"editable", "immutable"}:
                mode = "editable"
            filtered_defaults[cid] = {
                "mode": mode,
                "locked": bool(entry.get("locked", False)),
                "mandatory": False,
            }

        filtered_immutable_ids = [
            str(cid).strip()
            for cid in (request.immutable_calendar_ids or [])
            if str(cid).strip() and str(cid).strip() not in reserved_calendar_ids
        ]

        payload: dict[str, Any] = {
            "calendar_rules": {
                "immutable_keywords": request.immutable_keywords,
                "immutable_calendar_ids": filtered_immutable_ids,
                "staging_calendar_id": request.staging_calendar_id,
                "user_calendar_id": request.user_calendar_id,
                "intake_calendar_id": request.intake_calendar_id,
                "per_calendar_defaults": filtered_defaults,
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
        models = client.list_models() if ok else []
        return {"ok": ok, "message": message, "models": models}

    @app.get("/api/sync/status")
    def sync_status(limit: int = 20) -> dict[str, Any]:
        return {"runs": app.state.context.state_store.recent_sync_runs(limit=limit)}

    @app.get("/api/audit/events")
    def audit_events(limit: int = 100, run_id: int | None = None) -> dict[str, Any]:
        return {"events": app.state.context.state_store.recent_audit_events(limit=limit, run_id=run_id)}

    @app.get("/api/debug/runs/{run_id}")
    def debug_run(run_id: int, limit: int = 500) -> dict[str, Any]:
        runs = app.state.context.state_store.recent_sync_runs(limit=200)
        run = next((item for item in runs if int(item.get("id", 0)) == int(run_id)), None)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        events = app.state.context.state_store.recent_audit_events(limit=limit, run_id=run_id)
        return {"run": run, "events": events}

    @app.get("/api/metrics/ai-request-bytes")
    def ai_request_bytes(days: int = 90, limit: int = 5000) -> dict[str, Any]:
        points = app.state.context.state_store.ai_request_bytes_series(days=days, limit=limit)
        return {"points": points, "days": max(1, int(days))}

    @app.get("/api/ai/changes")
    def ai_changes(limit: int = 15) -> dict[str, Any]:
        events = app.state.context.state_store.recent_audit_events(limit=max(100, limit * 6))
        output: list[dict[str, Any]] = []
        config = app.state.context.config_manager.load()
        service: CalDAVService | None = None
        for event in events:
            if event.get("action") != "apply_ai_change":
                continue
            details = event.get("details", {}) or {}
            before_event = details.get("before_event") or {}
            after_event = details.get("after_event") or {}
            patch = details.get("patch") or []

            start_value = after_event.get("start") or details.get("start") or before_event.get("start") or ""
            end_value = after_event.get("end") or details.get("end") or before_event.get("end") or ""
            summary_value = (
                after_event.get("summary")
                or details.get("title")
                or before_event.get("summary")
                or ""
            )
            if isinstance(patch, list):
                for item in patch:
                    if not isinstance(item, dict):
                        continue
                    field = str(item.get("field", "")).strip()
                    after_value = item.get("after")
                    if field == "summary" and not summary_value:
                        summary_value = str(after_value or "")
                    elif field == "start" and not start_value:
                        start_value = str(after_value or "")
                    elif field == "end" and not end_value:
                        end_value = str(after_value or "")

            calendar_id = str(event.get("calendar_id", "") or "")
            uid = str(event.get("uid", "") or "")
            if (not summary_value or not start_value or not end_value) and calendar_id and uid:
                try:
                    if service is None:
                        service = CalDAVService(config.caldav)
                    current_event = service.get_event_by_uid(calendar_id, uid)
                    if current_event is not None:
                        if not summary_value:
                            summary_value = current_event.summary
                        if not start_value:
                            start_value = current_event.to_dict().get("start", "")
                        if not end_value:
                            end_value = current_event.to_dict().get("end", "")
                except Exception:
                    # Do not fail the whole endpoint when CalDAV lookup is unavailable.
                    pass

            title = str(
                summary_value
                or ""
            ).strip()
            if not title:
                title = uid or f"event#{event.get('id')}"
            reason_text = str(details.get("reason", "") or "").strip()
            if not reason_text:
                fields = details.get("fields") or []
                if isinstance(fields, list) and fields:
                    reason_text = f"AI adjusted fields: {', '.join(str(x) for x in fields)}"
                else:
                    reason_text = "Legacy record without reason"

            effective_patch: list[dict[str, Any]] = []
            if isinstance(patch, list):
                for item in patch:
                    if not isinstance(item, dict):
                        continue
                    before_val = str(item.get("before", "") or "")
                    after_val = str(item.get("after", "") or "")
                    if before_val == after_val:
                        continue
                    effective_patch.append(
                        {
                            "field": str(item.get("field", "") or ""),
                            "before": before_val,
                            "after": after_val,
                        }
                    )
            if not effective_patch:
                # Skip records that have no effective field changes.
                continue
            output.append(
                {
                    "audit_id": event.get("id"),
                    "created_at": event.get("created_at"),
                    "calendar_id": calendar_id,
                    "uid": uid,
                    "title": title,
                    "start": start_value,
                    "end": end_value,
                    "reason": reason_text,
                    "fields": details.get("fields") or [],
                    "patch": effective_patch,
                }
            )
            if len(output) >= max(1, limit):
                break
        return {"changes": output}

    @app.post("/api/ai/changes/undo")
    def undo_ai_change(request: AIChangeUndoRequest) -> dict[str, Any]:
        event = app.state.context.state_store.get_audit_event(request.audit_id)
        if event is None:
            raise HTTPException(status_code=404, detail="audit event not found")
        if event.get("action") != "apply_ai_change":
            raise HTTPException(status_code=400, detail="audit event is not an AI change")
        details = event.get("details", {}) or {}
        before_payload = details.get("before_event")
        if not isinstance(before_payload, dict):
            raise HTTPException(status_code=400, detail="undo data missing")
        before_event = _event_from_dict(before_payload)
        if not before_event.calendar_id or not before_event.uid:
            raise HTTPException(status_code=400, detail="undo event identity missing")

        expected_etag = str(details.get("expected_etag", "") or "").strip()
        if not expected_etag:
            after_payload = details.get("after_event")
            if isinstance(after_payload, dict):
                expected_etag = str(after_payload.get("etag", "") or "").strip()

        def _record_undo_failure(reason: str, *, current_etag: str = "") -> None:
            app.state.context.state_store.record_audit_event(
                calendar_id=before_event.calendar_id,
                uid=before_event.uid,
                action="undo_ai_change_failed",
                details={
                    "audit_id": request.audit_id,
                    "reason": reason,
                    "expected_etag": expected_etag,
                    "current_etag": current_etag,
                    "title": before_event.summary,
                },
            )

        config = app.state.context.config_manager.load()
        service = CalDAVService(config.caldav)
        current_event = None
        if hasattr(service, "get_event_by_uid"):
            current_event = service.get_event_by_uid(before_event.calendar_id, before_event.uid)
        if current_event is None and expected_etag:
            _record_undo_failure("target_event_not_found")
            raise HTTPException(status_code=404, detail="target event not found")
        if current_event is not None:
            if not expected_etag:
                _record_undo_failure("expected_etag_missing", current_etag=current_event.etag)
                raise HTTPException(status_code=400, detail="undo version metadata missing")
            if current_event.etag != expected_etag:
                _record_undo_failure("version_conflict", current_etag=current_event.etag)
                raise HTTPException(status_code=409, detail="事件已被后续修改，请手动确认")

        try:
            restored = service.upsert_event(before_event.calendar_id, before_event)
        except Exception as exc:
            _record_undo_failure(f"undo_apply_error: {exc}", current_etag=(current_event.etag if current_event is not None else ""))
            raise
        app.state.context.state_store.record_audit_event(
            calendar_id=restored.calendar_id,
            uid=restored.uid,
            action="undo_ai_change",
            details={
                "audit_id": request.audit_id,
                "title": restored.summary,
                "expected_etag": expected_etag,
                "before_undo_etag": (current_event.etag if current_event is not None else ""),
                "after_undo_etag": getattr(restored, "etag", ""),
            },
        )
        return {"message": "undo applied", "event": restored.to_dict()}

    @app.post("/api/ai/changes/revise")
    def revise_ai_change(request: AIChangeReviseRequest) -> dict[str, Any]:
        event = app.state.context.state_store.get_audit_event(request.audit_id)
        if event is None:
            raise HTTPException(status_code=404, detail="audit event not found")
        if event.get("action") != "apply_ai_change":
            raise HTTPException(status_code=400, detail="audit event is not an AI change")

        calendar_id = str(event.get("calendar_id", "")).strip()
        uid = str(event.get("uid", "")).strip()
        if not calendar_id or not uid:
            raise HTTPException(status_code=400, detail="target event identity missing")

        config = app.state.context.config_manager.load()
        service = CalDAVService(config.caldav)
        target_event = service.get_event_by_uid(calendar_id, uid)
        if target_event is None:
            raise HTTPException(status_code=404, detail="target event not found")

        updated_description, _, _ = set_ai_task_user_intent(
            target_event.description,
            config.task_defaults,
            request.instruction,
        )
        target_event.description = updated_description
        saved = service.upsert_event(calendar_id, target_event)
        app.state.context.state_store.record_audit_event(
            calendar_id=saved.calendar_id,
            uid=saved.uid,
            action="request_ai_revision",
            details={
                "audit_id": request.audit_id,
                "instruction": request.instruction,
                "title": saved.summary,
            },
        )
        app.state.context.scheduler.trigger_manual()
        return {"message": "revision request accepted", "event": saved.to_dict()}

    return app


app = create_app()


