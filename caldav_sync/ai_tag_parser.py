from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AIMeta:
    schema: Optional[int]
    type: Optional[str]
    lock: Optional[bool]
    estimated: Optional[timedelta]
    deadline: Optional[datetime]
    priority: Optional[str]
    extra: dict


AI_BLOCK_RE = re.compile(r"\[AI\](.*?)\[/AI\]", re.IGNORECASE | re.DOTALL)


def parse_ai_block(description: str) -> Optional[AIMeta]:
    match = AI_BLOCK_RE.search(description)
    if not match:
        return None
    block = match.group(1)
    data: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip().lower()] = value.strip()

    if not data:
        return None

    extra: dict[str, str] = {}
    schema = _parse_int(data.get("schema"))
    ai_type = data.get("type")
    lock = _parse_bool(data.get("lock"))
    estimated = _parse_duration(data.get("estimated"))
    deadline = _parse_datetime(data.get("deadline"))
    priority = data.get("priority")

    known_keys = {"schema", "type", "lock", "estimated", "deadline", "priority"}
    for key, value in data.items():
        if key not in known_keys:
            extra[key] = value

    return AIMeta(
        schema=schema,
        type=ai_type,
        lock=lock,
        estimated=estimated,
        deadline=deadline,
        priority=priority,
        extra=extra,
    )


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    value_lower = value.strip().lower()
    if value_lower in {"true", "1", "yes"}:
        return True
    if value_lower in {"false", "0", "no"}:
        return False
    return None


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_duration(value: Optional[str]) -> Optional[timedelta]:
    if not value:
        return None
    value = value.strip().upper()
    if value.startswith("PT"):
        hours = 0.0
        minutes = 0.0
        match = re.search(r"(\d+(?:\.\d+)?)H", value)
        if match:
            hours = float(match.group(1))
        match = re.search(r"(\d+(?:\.\d+)?)M", value)
        if match:
            minutes = float(match.group(1))
        return timedelta(hours=hours, minutes=minutes)
    match = re.match(r"(\d+(?:\.\d+)?)([HM])", value)
    if match:
        amount = float(match.group(1))
        unit = match.group(2)
        if unit == "H":
            return timedelta(hours=amount)
        return timedelta(minutes=amount)
    return None


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        logger.debug("Invalid datetime: %s", value)
        return None
