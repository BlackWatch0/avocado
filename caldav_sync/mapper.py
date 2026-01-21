from __future__ import annotations

from typing import Optional

from caldav_sync.ai_tag_parser import AIMeta
from caldav_sync.domain_models import FixedEvent, Task
from caldav_sync.ics_parser import Event


def map_event(event: Event, ai_meta: Optional[AIMeta]) -> FixedEvent | Task:
    if ai_meta is None:
        return _fixed_event_from(event)
    if ai_meta.lock is True:
        return _fixed_event_from(event)
    if ai_meta.type and ai_meta.type.lower() == "task" and ai_meta.lock is not True:
        return Task(
            uid=event.uid,
            duration=ai_meta.estimated,
            deadline=ai_meta.deadline,
            title=event.summary,
            lock=ai_meta.lock,
            source_href=event.href or "",
            collection_url=event.collection_url or "",
            description=event.description,
            priority=ai_meta.priority,
        )
    return _fixed_event_from(event)


def _fixed_event_from(event: Event) -> FixedEvent:
    return FixedEvent(
        uid=event.uid,
        start=event.start,
        end=event.end,
        title=event.summary,
        source_href=event.href or "",
        collection_url=event.collection_url or "",
        description=event.description,
        location=event.location,
    )
