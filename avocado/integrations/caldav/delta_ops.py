from __future__ import annotations

from datetime import datetime
from typing import Any

from avocado.core.models import EventRecord
from avocado.integrations.caldav.codec import decode_raw_ical, extract_etag, extract_uid_from_raw_ical, parse_resource


class DeltaOpsMixin:
    def list_window_index(self, calendar_id: str, start: datetime, end: datetime) -> list[dict[str, str]]:
        self._connect()
        calendar = self._get_calendar(calendar_id)
        resources = calendar.date_search(start=start, end=end, expand=True)
        output: list[dict[str, str]] = []
        for resource in resources:
            href = str(getattr(resource, "url", "") or "")
            raw_data = getattr(resource, "data", "")
            raw_ical = decode_raw_ical(raw_data)
            uid = extract_uid_from_raw_ical(raw_ical)
            etag = extract_etag(resource, raw_ical)
            if not uid:
                continue
            output.append({"uid": uid, "href": href, "etag": etag})
        return output

    def fetch_changes_by_token(
        self, calendar_id: str, sync_token: str | None
    ) -> dict[str, Any]:
        self._connect()
        calendar = self._get_calendar(calendar_id)
        try:
            updates = calendar.objects_by_sync_token(sync_token=sync_token, load_objects=False)
        except Exception as exc:
            return {
                "supported": False,
                "add_update": [],
                "delete": [],
                "next_token": sync_token or "",
                "error": f"{type(exc).__name__}: {exc}",
            }

        next_token = str(getattr(updates, "sync_token", "") or sync_token or "")
        add_update: list[EventRecord] = []
        deleted: list[dict[str, str]] = []
        for obj in updates:
            href = str(getattr(obj, "url", "") or "")
            uid = ""
            raw_data = getattr(obj, "data", "")
            if raw_data:
                uid = extract_uid_from_raw_ical(raw_data)
            try:
                obj.load()
                parsed = parse_resource(calendar_id, obj)
                if parsed.uid:
                    add_update.append(parsed)
                elif uid:
                    parsed.uid = uid
                    add_update.append(parsed)
            except Exception:
                deleted.append({"uid": uid, "href": href})
        return {
            "supported": True,
            "add_update": add_update,
            "delete": deleted,
            "next_token": next_token,
            "error": "",
        }
