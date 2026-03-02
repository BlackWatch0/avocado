from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from avocado.web_admin.context import AppContext
from avocado.web_admin.routes.ai import register_ai_routes
from avocado.web_admin.routes.calendars import register_calendar_routes
from avocado.web_admin.routes.config import register_config_routes
from avocado.web_admin.routes.logs import register_log_routes
from avocado.web_admin.routes.sync import register_sync_routes


def create_app() -> FastAPI:
    config_path = os.getenv("AVOCADO_CONFIG_PATH", "config.yaml")
    state_path = os.getenv("AVOCADO_STATE_PATH", "data/state.db")
    context = AppContext(config_path=config_path, state_path=state_path)
    module_dir = Path(__file__).resolve().parent.parent

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

    register_config_routes(app)
    register_calendar_routes(app)
    register_sync_routes(app)
    register_ai_routes(app)
    register_log_routes(app)

    return app


app = create_app()
