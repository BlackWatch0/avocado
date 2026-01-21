from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional


@dataclass(frozen=True)
class FixedEvent:
    uid: str
    start: date | datetime
    end: date | datetime
    title: str
    source_href: str
    collection_url: str
    description: Optional[str] = None
    location: Optional[str] = None


@dataclass(frozen=True)
class Task:
    uid: str
    duration: Optional[timedelta]
    deadline: Optional[datetime]
    title: str
    lock: Optional[bool]
    source_href: str
    collection_url: str
    description: Optional[str] = None
    priority: Optional[str] = None
