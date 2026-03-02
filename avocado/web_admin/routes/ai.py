from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException

from avocado.ai_client import OpenAICompatibleClient
from avocado.integrations.caldav import CalDAVService
from avocado.task_block import set_ai_task_user_intent
from avocado.web_admin.schemas import AIChangeReviseRequest, AIChangeUndoRequest
from avocado.web_admin.utils import event_from_dict


def register_ai_routes(app: FastAPI) -> None:
    @app.post("/api/ai/test")
    def test_ai_connectivity() -> dict[str, Any]:
        config = app.state.context.config_manager.load()
        request_payload = {
            "model": config.ai.model,
            "messages": [{"role": "user", "content": "Reply with: OK"}],
            "temperature": 0,
            "max_tokens": 8,
        }
        request_bytes = len(json.dumps(request_payload, ensure_ascii=False).encode("utf-8"))
        client = OpenAICompatibleClient(config.ai)
        ok, message = client.test_connectivity()
        usage = dict(getattr(client, "last_usage", {}) or {})
        app.state.context.state_store.record_audit_event(
            calendar_id="system",
            uid="ai",
            action="ai_request",
            details={
                "trigger": "admin_ai_test",
                "request_bytes": request_bytes,
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
                "target_events_count": 0,
                "planning_events_count": 0,
                "ai_input_hash": "",
            },
        )
        models = client.list_models() if ok else []
        return {"ok": ok, "message": message, "models": models}

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
        before_event = event_from_dict(before_payload)
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
