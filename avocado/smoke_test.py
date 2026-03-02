from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from avocado.ai_client import OpenAICompatibleClient
from avocado.caldav_client import CalDAVService
from avocado.config_manager import ConfigManager
from avocado.models import parse_iso_datetime, serialize_datetime
from avocado.state_store import StateStore
from avocado.sync_engine import SyncEngine


def _line(title: str, payload: Any = "") -> None:
    if payload == "":
        print(f"[SMOKE] {title}")
        return
    print(f"[SMOKE] {title}: {payload}")


def _ok(title: str, payload: Any = "") -> None:
    if payload == "":
        print(f"[ OK ] {title}")
        return
    print(f"[ OK ] {title}: {payload}")


def _warn(title: str, payload: Any = "") -> None:
    if payload == "":
        print(f"[WARN] {title}")
        return
    print(f"[WARN] {title}: {payload}")


def _fail(title: str, payload: Any = "") -> None:
    if payload == "":
        print(f"[FAIL] {title}")
        return
    print(f"[FAIL] {title}: {payload}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Avocado integration smoke test using current config.yaml"
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--state", default="data/state.db", help="Path to state sqlite db")
    parser.add_argument(
        "--skip-caldav", action="store_true", help="Skip CalDAV connectivity/calendar checks"
    )
    parser.add_argument("--skip-ai", action="store_true", help="Skip AI connectivity checks")
    parser.add_argument(
        "--run-sync",
        action="store_true",
        help="Run one manual-window sync after checks (may write data)",
    )
    parser.add_argument(
        "--start",
        default="",
        help="Sync window start ISO8601 (used only with --run-sync)",
    )
    parser.add_argument(
        "--end",
        default="",
        help="Sync window end ISO8601 (used only with --run-sync)",
    )
    return parser.parse_args()


def _window_from_args(config_window_days: int, start_text: str, end_text: str) -> tuple[datetime, datetime]:
    if bool(start_text) ^ bool(end_text):
        raise ValueError("--start and --end must be provided together")
    if start_text and end_text:
        start = parse_iso_datetime(start_text)
        end = parse_iso_datetime(end_text)
        if start is None or end is None:
            raise ValueError("Invalid --start/--end ISO8601 datetime")
        if end <= start:
            raise ValueError("--end must be later than --start")
        return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=max(1, int(config_window_days)))
    return start, end


def main() -> int:
    args = _parse_args()
    _line("Loading config", args.config)
    config = ConfigManager(args.config).load()
    failures: list[str] = []

    _line(
        "Config summary",
        json.dumps(
            {
                "caldav_base_url": config.caldav.base_url,
                "caldav_username": config.caldav.username,
                "ai_base_url": config.ai.base_url,
                "ai_model": config.ai.model,
                "timezone": config.sync.timezone,
                "window_days": config.sync.window_days,
                "stack_calendar_id": config.calendar_rules.stack_calendar_id,
                "user_calendar_id": config.calendar_rules.user_calendar_id,
                "new_calendar_id": config.calendar_rules.new_calendar_id,
            },
            ensure_ascii=False,
        ),
    )

    if not args.skip_caldav:
        _line("Checking CalDAV")
        try:
            service = CalDAVService(config.caldav)
            calendars = service.list_calendars()
            _ok("CalDAV connected", f"{len(calendars)} calendars found")

            stack_info = service.ensure_managed_calendar(
                config.calendar_rules.stack_calendar_id,
                config.calendar_rules.stack_calendar_name,
            )
            user_info = service.ensure_managed_calendar(
                config.calendar_rules.user_calendar_id,
                config.calendar_rules.user_calendar_name,
            )
            new_info = service.ensure_managed_calendar(
                config.calendar_rules.new_calendar_id,
                config.calendar_rules.new_calendar_name,
            )
            _ok("Managed calendars", f"stack={stack_info.calendar_id}")
            _ok("Managed calendars", f"user={user_info.calendar_id}")
            _ok("Managed calendars", f"new={new_info.calendar_id}")

            start, end = _window_from_args(config.sync.window_days, args.start, args.end)
            _line("Event sample window", f"{serialize_datetime(start)} -> {serialize_datetime(end)}")
            for cal in calendars:
                try:
                    events = service.fetch_events(cal.calendar_id, start, end)
                    _line("Calendar events", f"{cal.name}: {len(events)}")
                except Exception as exc:
                    _warn("Calendar fetch failed", f"{cal.calendar_id} {type(exc).__name__}: {exc}")
        except Exception as exc:
            failures.append(f"caldav:{type(exc).__name__}:{exc}")
            _fail("CalDAV check failed", f"{type(exc).__name__}: {exc}")
    else:
        _warn("Skip CalDAV checks")

    if not args.skip_ai:
        _line("Checking AI connectivity")
        try:
            client = OpenAICompatibleClient(config.ai)
            ok, message = client.test_connectivity()
            if ok:
                _ok("AI connectivity", message)
                models = client.list_models()
                if models:
                    _ok("AI model list", f"{len(models)} models; first={models[0]}")
                else:
                    _warn("AI model list empty")
            else:
                failures.append(f"ai:{message}")
                _fail("AI connectivity failed", message)
        except Exception as exc:
            failures.append(f"ai:{type(exc).__name__}:{exc}")
            _fail("AI check failed", f"{type(exc).__name__}: {exc}")
    else:
        _warn("Skip AI checks")

    if args.run_sync:
        _line("Running manual-window sync")
        try:
            start, end = _window_from_args(config.sync.window_days, args.start, args.end)
            engine = SyncEngine(ConfigManager(args.config), StateStore(args.state))
            result = engine.run_once(
                trigger="manual-window",
                window_start_override=start,
                window_end_override=end,
            )
            if result.status == "success":
                _ok(
                    "Sync result",
                    f"changes={result.changes_applied} conflicts={result.conflicts} duration_ms={result.duration_ms}",
                )
            else:
                failures.append(f"sync:{result.message}")
                _fail("Sync failed", result.message)
        except Exception as exc:
            failures.append(f"sync:{type(exc).__name__}:{exc}")
            _fail("Sync exception", f"{type(exc).__name__}: {exc}")
    else:
        _warn("Skip sync run (--run-sync not set)")

    if failures:
        _fail("Smoke test completed with failures", len(failures))
        for item in failures:
            print(f"  - {item}")
        return 1

    _ok("Smoke test completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
