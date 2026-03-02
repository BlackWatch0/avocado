from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from avocado.timezone_utils import detect_host_timezone_name, resolve_effective_timezone
from avocado.web_admin.schemas import ConfigUpdateRequest
from avocado.web_admin.utils import masked_meta, sanitize_config_payload


def register_config_routes(app: FastAPI) -> None:
    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        return app.state.context.config_manager.masked()

    @app.put("/api/config")
    def put_config(request: ConfigUpdateRequest) -> dict[str, Any]:
        if not isinstance(request.payload, dict):
            raise HTTPException(status_code=400, detail="payload must be an object")
        current = app.state.context.config_manager.load().to_dict()
        sanitized_payload = sanitize_config_payload(request.payload, current)
        updated = app.state.context.config_manager.update(sanitized_payload)
        return {
            "message": "config updated",
            "config": updated.to_dict(),
        }

    @app.get("/api/config/raw")
    def get_config_raw() -> dict[str, Any]:
        raw = app.state.context.config_manager.load().to_dict()
        masked = app.state.context.config_manager.masked()
        return {"config": masked, "meta": masked_meta(raw)}

    @app.get("/api/system/timezone")
    def get_system_timezone() -> dict[str, str]:
        config = app.state.context.config_manager.load()
        host_timezone = detect_host_timezone_name()
        timezone_source = str(getattr(config.sync, "timezone_source", "host") or "host")
        configured_timezone = str(config.sync.timezone or "UTC")
        effective_timezone = resolve_effective_timezone(
            configured_timezone=configured_timezone,
            timezone_source=timezone_source,
        )
        return {
            "host_timezone": host_timezone,
            "timezone_source": timezone_source,
            "configured_timezone": configured_timezone,
            "effective_timezone": effective_timezone,
        }
