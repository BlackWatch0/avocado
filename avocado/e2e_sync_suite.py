from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from avocado.ai_client import OpenAICompatibleClient
from avocado.caldav_client import CalDAVService
from avocado.config_manager import ConfigManager
from avocado.models import EventRecord, TaskDefaultsConfig, parse_iso_datetime, serialize_datetime
from avocado.state_store import StateStore
from avocado.sync_engine import SyncEngine
from avocado.task_block import ensure_ai_task_block, parse_ai_task_block, upsert_ai_task_block


@dataclass
class CaseResult:
    name: str
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)


def _setup_logger(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("avocado_e2e")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    return logger


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Avocado real-environment E2E suite (reads config.yaml, triggers sync, writes logs)."
    )
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--state", default="data/state.db", help="State DB path")
    parser.add_argument("--window-days", type=int, default=7, help="Primary test window days")
    parser.add_argument(
        "--log-file",
        default="",
        help="Optional log file path. Default: data/test_logs/e2e_sync_suite_<timestamp>.log",
    )
    parser.add_argument(
        "--start",
        default="",
        help="Optional manual-window start ISO8601. Must pair with --end.",
    )
    parser.add_argument(
        "--end",
        default="",
        help="Optional manual-window end ISO8601. Must pair with --start.",
    )
    return parser.parse_args()


def _window_from_args(args: argparse.Namespace) -> tuple[datetime, datetime]:
    if bool(args.start) ^ bool(args.end):
        raise ValueError("--start and --end must be provided together")
    if args.start and args.end:
        start = parse_iso_datetime(args.start)
        end = parse_iso_datetime(args.end)
        if start is None or end is None:
            raise ValueError("Invalid --start/--end datetime")
        if end <= start:
            raise ValueError("--end must be later than --start")
        return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=max(1, int(args.window_days))) - timedelta(microseconds=1)
    return start, end


def _build_ai_task_description(
    *,
    base_text: str,
    locked: bool,
    user_intent: str,
) -> str:
    defaults = TaskDefaultsConfig(
        locked=locked,
        editable_fields=["start", "end", "summary", "location", "description"],
    )
    description, payload, _ = ensure_ai_task_block(base_text, defaults)
    payload["locked"] = bool(locked)
    payload["editable_fields"] = ["start", "end", "summary", "location", "description"]
    payload["user_intent"] = str(user_intent).strip()
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    return upsert_ai_task_block(description, payload)


def _extract_run_id(message: str) -> int | None:
    match = re.search(r"run_id=(\d+)", str(message))
    if not match:
        return None
    return int(match.group(1))


def _find_case_event(service: CalDAVService, calendar_id: str, uid: str) -> EventRecord | None:
    try:
        return service.get_event_by_uid(calendar_id, uid)
    except Exception:
        return None


def _delete_if_exists(service: CalDAVService, calendar_id: str, uid: str, logger: logging.Logger) -> None:
    try:
        ok = service.delete_event(calendar_id, uid=uid)
        logger.info("cleanup delete_event calendar=%s uid=%s ok=%s", calendar_id, uid, ok)
    except Exception as exc:
        logger.warning("cleanup delete failed calendar=%s uid=%s err=%s", calendar_id, uid, exc)


def main() -> int:
    args = _parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = Path(args.log_file) if args.log_file else Path("data/test_logs") / f"e2e_sync_suite_{timestamp}.log"
    logger = _setup_logger(log_path)
    logger.info("E2E suite start config=%s state=%s", args.config, args.state)

    cfg_mgr = ConfigManager(args.config)
    config = cfg_mgr.load()
    store = StateStore(args.state)
    engine = SyncEngine(cfg_mgr, store)
    service = CalDAVService(config.caldav)
    ai_client = OpenAICompatibleClient(config.ai)
    results: list[CaseResult] = []
    created_user_uids: list[str] = []

    # 1) config read/write roundtrip test
    try:
        original_interval = config.sync.interval_seconds
        candidate = original_interval + 1 if original_interval < 3600 else max(30, original_interval - 1)
        logger.info("config roundtrip before interval_seconds=%s candidate=%s", original_interval, candidate)
        cfg_mgr.update({"sync": {"interval_seconds": candidate}})
        after = cfg_mgr.load()
        cfg_mgr.update({"sync": {"interval_seconds": original_interval}})
        restored = cfg_mgr.load()
        passed = after.sync.interval_seconds == candidate and restored.sync.interval_seconds == original_interval
        results.append(
            CaseResult(
                name="config_write_read_roundtrip",
                passed=passed,
                details={
                    "before": original_interval,
                    "after": after.sync.interval_seconds,
                    "restored": restored.sync.interval_seconds,
                },
            )
        )
    except Exception as exc:
        results.append(
            CaseResult(
                name="config_write_read_roundtrip",
                passed=False,
                details={"error": f"{type(exc).__name__}: {exc}"},
            )
        )

    # Reload latest config after roundtrip.
    config = cfg_mgr.load()
    service = CalDAVService(config.caldav)

    # 2) connectivity checks
    try:
        calendars = service.list_calendars()
        stack = service.ensure_managed_calendar(
            config.calendar_rules.stack_calendar_id,
            config.calendar_rules.stack_calendar_name,
        )
        user = service.ensure_managed_calendar(
            config.calendar_rules.user_calendar_id,
            config.calendar_rules.user_calendar_name,
        )
        new_calendar = service.ensure_managed_calendar(
            config.calendar_rules.new_calendar_id,
            config.calendar_rules.new_calendar_name,
        )
        logger.info(
            "caldav calendars=%s stack=%s user=%s new=%s",
            len(calendars),
            stack.calendar_id,
            user.calendar_id,
            new_calendar.calendar_id,
        )
        results.append(
            CaseResult(
                name="caldav_connectivity",
                passed=True,
                details={
                    "calendar_count": len(calendars),
                    "stack": stack.calendar_id,
                    "user": user.calendar_id,
                    "new": new_calendar.calendar_id,
                },
            )
        )
    except Exception as exc:
        results.append(
            CaseResult(
                name="caldav_connectivity",
                passed=False,
                details={"error": f"{type(exc).__name__}: {exc}"},
            )
        )
        logger.exception("caldav connectivity failed")
        # Without caldav, we cannot continue.
        summary = {"passed": False, "results": [asdict(r) for r in results], "log_file": str(log_path)}
        logger.info("SUMMARY %s", json.dumps(summary, ensure_ascii=False))
        return 1

    try:
        ok, message = ai_client.test_connectivity()
        results.append(
            CaseResult(
                name="ai_connectivity",
                passed=bool(ok),
                details={"message": message, "model": config.ai.model},
            )
        )
        logger.info("ai connectivity ok=%s message=%s", ok, message)
    except Exception as exc:
        results.append(
            CaseResult(
                name="ai_connectivity",
                passed=False,
                details={"error": f"{type(exc).__name__}: {exc}"},
            )
        )
        logger.exception("ai connectivity failed")

    # 3) prepare test events in user-layer
    window_start, window_end = _window_from_args(args)
    base_day = (window_start + timedelta(days=1)).date()
    move_start = datetime.combine(base_day, time(10, 0), tzinfo=timezone.utc)
    move_end = move_start + timedelta(minutes=30)
    fixed_start = datetime.combine(base_day, time(11, 0), tzinfo=timezone.utc)
    fixed_end = fixed_start + timedelta(minutes=30)

    move_uid = str(uuid4())
    fixed_uid = str(uuid4())
    created_user_uids.extend([move_uid, fixed_uid])

    move_before = EventRecord(
        calendar_id=user.calendar_id,
        uid=move_uid,
        summary=f"[AVO-E2E] Move Event {timestamp}",
        description=_build_ai_task_description(
            base_text="[AVO-E2E] Please move this schedule and annotate result.",
            locked=False,
            user_intent="Move this event 30 minutes earlier and append [E2E-MOVED] to description.",
        ),
        location="E2E Lab",
        start=move_start,
        end=move_end,
        source="user",
        locked=False,
    )
    fixed_before = EventRecord(
        calendar_id=user.calendar_id,
        uid=fixed_uid,
        summary=f"[AVO-E2E] Fixed Event {timestamp}",
        description=_build_ai_task_description(
            base_text="[AVO-E2E] Fixed schedule should never move.",
            locked=True,
            user_intent="Move this event 30 minutes earlier.",
        ),
        location="E2E Lab",
        start=fixed_start,
        end=fixed_end,
        source="user",
        locked=True,
    )

    service.upsert_event(user.calendar_id, move_before)
    service.upsert_event(user.calendar_id, fixed_before)
    logger.info(
        "created test events user_calendar=%s move_uid=%s fixed_uid=%s",
        user.calendar_id,
        move_uid,
        fixed_uid,
    )

    # 4) run sync
    sync_result = engine.run_once(
        trigger="manual-window",
        window_start_override=window_start,
        window_end_override=window_end,
    )
    run_id = _extract_run_id(sync_result.message)
    logger.info(
        "sync result status=%s changes=%s conflicts=%s message=%s",
        sync_result.status,
        sync_result.changes_applied,
        sync_result.conflicts,
        sync_result.message,
    )
    run_events = store.recent_audit_events(limit=1000, run_id=run_id) if run_id else []
    logger.info("sync run_id=%s audit_events=%s", run_id, len(run_events))

    # 5) validate cases
    move_after = _find_case_event(service, user.calendar_id, move_uid)
    fixed_after = _find_case_event(service, user.calendar_id, fixed_uid)

    move_audit = [
        e
        for e in run_events
        if str(e.get("uid", "")) == move_uid and str(e.get("action", "")) == "apply_ai_change"
    ]
    move_changed = False
    if move_after is not None:
        move_changed = (move_after.start != move_before.start) or ("[E2E-MOVED]" in (move_after.description or ""))
    if not move_changed and move_audit:
        details = move_audit[0].get("details", {}) or {}
        fields = set(details.get("fields", []) or [])
        move_changed = "start" in fields or "description" in fields
    results.append(
        CaseResult(
            name="ai_move_instruction",
            passed=move_changed,
            details={
                "before_start": serialize_datetime(move_before.start),
                "after_start": serialize_datetime(move_after.start if move_after else None),
                "applied_audit_count": len(move_audit),
                "after_description_head": (move_after.description[:180] if move_after else ""),
            },
        )
    )

    fixed_unchanged = False
    fixed_skip_logs = [
        e
        for e in run_events
        if str(e.get("uid", "")) == fixed_uid and str(e.get("action", "")) == "ai_change_skipped_locked"
    ]
    if fixed_after is not None:
        fixed_unchanged = fixed_after.start == fixed_before.start and fixed_after.end == fixed_before.end
    results.append(
        CaseResult(
            name="fixed_schedule_locked_protection",
            passed=bool(fixed_unchanged),
            details={
                "before_start": serialize_datetime(fixed_before.start),
                "after_start": serialize_datetime(fixed_after.start if fixed_after else None),
                "skip_locked_logs": len(fixed_skip_logs),
            },
        )
    )

    # 6) dump action stats for run
    action_counts: dict[str, int] = {}
    for item in run_events:
        action = str(item.get("action", ""))
        action_counts[action] = action_counts.get(action, 0) + 1
    logger.info("run action counts: %s", json.dumps(action_counts, ensure_ascii=False, sort_keys=True))

    # 7) cleanup
    stack_calendar_id = stack.calendar_id
    for uid in created_user_uids:
        _delete_if_exists(service, user.calendar_id, uid, logger)
        _delete_if_exists(service, stack_calendar_id, uid, logger)

    all_passed = all(item.passed for item in results)
    summary = {
        "passed": all_passed,
        "run_id": run_id,
        "sync_result": sync_result.to_dict(),
        "action_counts": action_counts,
        "results": [asdict(item) for item in results],
        "log_file": str(log_path),
        "window_start": serialize_datetime(window_start),
        "window_end": serialize_datetime(window_end),
    }
    logger.info("SUMMARY %s", json.dumps(summary, ensure_ascii=False))

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
