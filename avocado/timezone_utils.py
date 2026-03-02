from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _is_valid_timezone(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        ZoneInfo(text)
        return True
    except Exception:
        return False


def _extract_localtime_symlink_timezone(localtime_path: Path = Path("/etc/localtime")) -> str:
    try:
        if not localtime_path.exists() or not localtime_path.is_symlink():
            return ""
        resolved = str(localtime_path.resolve())
    except Exception:
        return ""
    marker = "/zoneinfo/"
    idx = resolved.find(marker)
    if idx < 0:
        return ""
    candidate = resolved[idx + len(marker) :].strip("/")
    return candidate


def detect_host_timezone_name() -> str:
    candidates: list[str] = []
    for key in ("AVOCADO_HOST_TIMEZONE", "TZ"):
        value = str(os.getenv(key, "")).strip()
        if value:
            candidates.append(value)

    timezone_file = Path("/etc/timezone")
    if timezone_file.exists():
        try:
            value = timezone_file.read_text(encoding="utf-8").strip()
            if value:
                candidates.append(value)
        except Exception:
            pass

    symlink_timezone = _extract_localtime_symlink_timezone()
    if symlink_timezone:
        candidates.append(symlink_timezone)

    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is not None:
        key = getattr(local_tz, "key", "")
        if key:
            candidates.append(str(key))
        text = str(local_tz).strip()
        if text:
            candidates.append(text)

    for candidate in candidates:
        if _is_valid_timezone(candidate):
            return candidate
    return "UTC"


def resolve_effective_timezone(*, configured_timezone: str, timezone_source: str) -> str:
    source = str(timezone_source or "").strip().lower()
    if source == "host":
        return detect_host_timezone_name()

    configured = str(configured_timezone or "").strip() or "UTC"
    if _is_valid_timezone(configured):
        return configured
    return "UTC"
