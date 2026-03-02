from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from avocado.caldav_client import CalDAVService
from avocado.config_manager import ConfigManager
from avocado.models import EventRecord, serialize_datetime
from avocado.state_store import StateStore
from avocado.sync_engine import SyncEngine, _staging_uid


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run user-defined UTF-8 calendar cases against real CalDAV + sync engine."
    )
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--state", default="data/state.db", help="State DB path")
    parser.add_argument(
        "--cases",
        default="tests/fixtures/user_cases_zh.json",
        help="UTF-8 JSON case file path",
    )
    parser.add_argument(
        "--log-file",
        default="",
        help="Optional log output path. Default: data/test_logs/user_cases_<timestamp>.json",
    )
    return parser.parse_args()


def _parse_hhmm(value: str) -> tuple[int, int]:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", text):
        raise ValueError(f"Invalid time '{value}', expected HH:MM")
    hour, minute = text.split(":")
    return int(hour), int(minute)


def _resolve_datetime_utc(
    *,
    base_local_date: datetime,
    day_offset: int,
    hhmm: str,
    local_tz: ZoneInfo,
) -> datetime:
    hour, minute = _parse_hhmm(hhmm)
    target_date = base_local_date.date() + timedelta(days=int(day_offset))
    return datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        hour,
        minute,
        tzinfo=local_tz,
    ).astimezone(timezone.utc)


def _extract_run_id(message: str) -> int | None:
    match = re.search(r"run_id=(\d+)", str(message))
    if not match:
        return None
    return int(match.group(1))


def _evaluate_case(
    *,
    expect: str,
    before_start: datetime,
    before_end: datetime,
    before_description: str,
    after: EventRecord | None,
) -> tuple[bool, dict[str, object]]:
    after_start = after.start if after else None
    after_end = after.end if after else None
    after_description = after.description if after else ""

    moved = before_start != after_start or before_end != after_end
    description_changed = before_description != after_description

    delta_start_minutes = None
    delta_end_minutes = None
    if after_start and after_end:
        delta_start_minutes = int((after_start - before_start).total_seconds() // 60)
        delta_end_minutes = int((after_end - before_end).total_seconds() // 60)

    passed = False
    if expect == "move_earlier_30m":
        passed = delta_start_minutes == -30 and delta_end_minutes == -30
    elif expect == "locked_not_moved":
        passed = not moved
    elif expect == "no_intent_not_moved":
        passed = not moved
    elif expect == "desc_update_only":
        passed = (not moved) and description_changed
    elif expect == "desc_update_no_time_change":
        passed = (not moved) and description_changed
    elif expect == "intake_import_keep_time":
        passed = not moved

    details: dict[str, object] = {
        "passed": bool(passed),
        "before_start": serialize_datetime(before_start),
        "after_start": serialize_datetime(after_start),
        "before_end": serialize_datetime(before_end),
        "after_end": serialize_datetime(after_end),
        "delta_start_minutes": delta_start_minutes,
        "delta_end_minutes": delta_end_minutes,
        "moved": moved,
        "description_changed": description_changed,
    }
    return bool(passed), details


def main() -> int:
    args = _parse_args()
    cfg_mgr = ConfigManager(args.config)
    config = cfg_mgr.load()
    service = CalDAVService(config.caldav)
    store = StateStore(args.state)
    engine = SyncEngine(cfg_mgr, store)

    # Force UTF-8 read for Chinese descriptions and AI Task text.
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Case file must be a non-empty JSON list")

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

    local_tz = ZoneInfo(config.sync.timezone or "UTC")
    now_local = datetime.now(local_tz)

    created_events: list[dict[str, object]] = []
    min_day_offset = None
    max_day_offset = None

    for item in cases:
        case = dict(item or {})
        day_offset = int(case.get("day_offset", 1))
        min_day_offset = day_offset if min_day_offset is None else min(min_day_offset, day_offset)
        max_day_offset = day_offset if max_day_offset is None else max(max_day_offset, day_offset)
        source_calendar = str(case.get("source_calendar", "user")).strip().lower() or "user"
        if source_calendar not in {"user", "intake"}:
            raise ValueError(f"Unsupported source_calendar: {source_calendar}")

        start_utc = _resolve_datetime_utc(
            base_local_date=now_local,
            day_offset=day_offset,
            hhmm=str(case.get("start_local", "")).strip(),
            local_tz=local_tz,
        )
        end_utc = _resolve_datetime_utc(
            base_local_date=now_local,
            day_offset=day_offset,
            hhmm=str(case.get("end_local", "")).strip(),
            local_tz=local_tz,
        )

        raw_uid = str(uuid4())
        target_calendar_id = user_info.calendar_id if source_calendar == "user" else intake_info.calendar_id
        expected_user_uid = raw_uid if source_calendar == "user" else _staging_uid(intake_info.calendar_id, raw_uid)
        event = EventRecord(
            calendar_id=target_calendar_id,
            uid=raw_uid,
            summary=str(case.get("name", "")).strip() or "(Untitled)",
            description=str(case.get("description", "")),
            location=str(case.get("location", "")),
            start=start_utc,
            end=end_utc,
            source=source_calendar,
            locked=bool(case.get("locked", False)),
        )
        service.upsert_event(target_calendar_id, event)
        created_events.append(
            {
                "name": event.summary,
                "expect": str(case.get("expect", "")).strip(),
                "source_calendar": source_calendar,
                "raw_uid": raw_uid,
                "expected_user_uid": expected_user_uid,
                "before": {
                    "start": serialize_datetime(start_utc),
                    "end": serialize_datetime(end_utc),
                    "description": event.description,
                },
            }
        )

    assert min_day_offset is not None and max_day_offset is not None
    window_start_local = datetime(
        now_local.year,
        now_local.month,
        now_local.day,
        0,
        0,
        tzinfo=local_tz,
    )
    window_start_local = window_start_local + timedelta(days=min_day_offset)
    window_end_local = datetime(
        now_local.year,
        now_local.month,
        now_local.day,
        23,
        59,
        59,
        999999,
        tzinfo=local_tz,
    )
    window_end_local = window_end_local + timedelta(days=max_day_offset)

    window_start = window_start_local.astimezone(timezone.utc)
    window_end = window_end_local.astimezone(timezone.utc)

    sync_result = engine.run_once(
        trigger="manual-window",
        window_start_override=window_start,
        window_end_override=window_end,
    )
    run_id = _extract_run_id(sync_result.message)
    run_events = store.recent_audit_events(limit=4000, run_id=run_id) if run_id else []

    checks: list[dict[str, object]] = []
    for item in created_events:
        raw_uid = str(item["raw_uid"])
        expected_user_uid = str(item["expected_user_uid"])
        before = dict(item["before"])
        before_start = datetime.fromisoformat(str(before["start"]))
        before_end = datetime.fromisoformat(str(before["end"]))
        before_description = str(before["description"])
        after_user = service.get_event_by_uid(user_info.calendar_id, expected_user_uid)
        after_stage = service.get_event_by_uid(stage_info.calendar_id, expected_user_uid)
        after_intake_raw = service.get_event_by_uid(intake_info.calendar_id, raw_uid)
        passed, details = _evaluate_case(
            expect=str(item["expect"]),
            before_start=before_start,
            before_end=before_end,
            before_description=before_description,
            after=after_user,
        )
        audit_actions = [
            str(audit_event.get("action", ""))
            for audit_event in run_events
            if str(audit_event.get("uid", "")) in {raw_uid, expected_user_uid}
        ]
        calendar_assertions = {
            "user_event_exists": after_user is not None,
            "stage_event_exists": after_stage is not None,
            "intake_raw_event_exists": after_intake_raw is not None,
        }
        calendar_passed = (
            calendar_assertions["user_event_exists"]
            and calendar_assertions["stage_event_exists"]
            and (not calendar_assertions["intake_raw_event_exists"])
        )
        overall_passed = bool(passed and calendar_passed)
        checks.append(
            {
                "name": str(item["name"]),
                "source_calendar": str(item["source_calendar"]),
                "uid": raw_uid,
                "expected_user_uid": expected_user_uid,
                "expect": str(item["expect"]),
                "passed": overall_passed,
                "behavior_passed": bool(passed),
                "calendar_passed": bool(calendar_passed),
                **details,
                "calendar_assertions": calendar_assertions,
                "audit_actions": sorted(set(audit_actions)),
            }
        )

    passed_all = all(bool(item.get("passed")) for item in checks)
    session = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = Path(args.log_file) if args.log_file else Path("data/test_logs") / f"user_cases_{session}.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session": session,
        "principal_username": config.caldav.username,
        "managed_calendars": {
            "stage": stage_info.calendar_id,
            "user": user_info.calendar_id,
            "intake": intake_info.calendar_id,
        },
        "window_start": serialize_datetime(window_start),
        "window_end": serialize_datetime(window_end),
        "sync_result": sync_result.to_dict(),
        "run_id": run_id,
        "checks": checks,
        "created_events": created_events,
        "kept_for_manual_inspection": True,
        "passed_all": passed_all,
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "log_file": str(log_path),
                "run_id": run_id,
                "passed_all": passed_all,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
