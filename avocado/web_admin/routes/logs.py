from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException


def register_log_routes(app: FastAPI) -> None:
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
