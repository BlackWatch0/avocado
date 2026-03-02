from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from avocado.core.models import parse_iso_datetime
from avocado.web_admin.schemas import CustomWindowSyncRequest


def register_sync_routes(app: FastAPI) -> None:
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

    @app.get("/api/sync/status")
    def sync_status(limit: int = 20) -> dict[str, Any]:
        return {"runs": app.state.context.state_store.recent_sync_runs(limit=limit)}
