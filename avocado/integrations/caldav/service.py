from __future__ import annotations

from typing import Any

from avocado.core.models import CalendarInfo, CalDAVConfig
from avocado.integrations.caldav.calendar_ops import CalendarOpsMixin
from avocado.integrations.caldav.delta_ops import DeltaOpsMixin
from avocado.integrations.caldav.helpers import (
    caldav,
    normalize_calendar_id,
    normalize_calendar_name,
    normalize_calendar_path,
)


class CalDAVService(CalendarOpsMixin, DeltaOpsMixin):
    def __init__(self, config: CalDAVConfig) -> None:
        self.config = config
        self._client: Any = None
        self._principal: Any = None
        self._calendar_cache: dict[str, Any] = {}

    def _require_dependency(self) -> None:
        if caldav is None:
            raise RuntimeError("caldav dependency is not installed.")

    def _connect(self) -> None:
        self._require_dependency()
        if self._principal is not None:
            return
        if not self.config.base_url or not self.config.username:
            raise RuntimeError("CalDAV config is incomplete.")
        self._client = caldav.DAVClient(
            url=self.config.base_url,
            username=self.config.username,
            password=self.config.password,
        )
        self._principal = self._client.principal()

    def list_calendars(self) -> list[CalendarInfo]:
        self._connect()
        self._calendar_cache = {}
        calendars: list[CalendarInfo] = []
        for calendar in self._principal.calendars():
            calendar_id = str(calendar.url)
            name = getattr(calendar, "name", "") or calendar_id
            self._calendar_cache[calendar_id] = calendar
            calendars.append(CalendarInfo(calendar_id=calendar_id, name=name, url=calendar_id))
        return calendars

    def _get_calendar(self, calendar_id: str) -> Any:
        if calendar_id in self._calendar_cache:
            return self._calendar_cache[calendar_id]
        for calendar in self._principal.calendars():
            cid = str(calendar.url)
            self._calendar_cache[cid] = calendar
        target_norm = normalize_calendar_id(calendar_id)
        target_path = normalize_calendar_path(calendar_id)
        if target_norm or target_path:
            for cid, calendar in self._calendar_cache.items():
                if target_norm and normalize_calendar_id(cid) == target_norm:
                    return calendar
                if target_path and normalize_calendar_path(cid) == target_path:
                    return calendar
        if calendar_id not in self._calendar_cache:
            raise RuntimeError(f"Calendar not found: {calendar_id}")
        return self._calendar_cache[calendar_id]

    def ensure_managed_calendar(self, calendar_id: str, calendar_name: str) -> CalendarInfo:
        self._connect()
        calendars = self.list_calendars()
        calendar_id_raw = str(calendar_id or "").strip()
        calendar_id_norm = normalize_calendar_id(calendar_id)
        calendar_id_path = normalize_calendar_path(calendar_id)
        if calendar_id_norm:
            for info in calendars:
                if normalize_calendar_id(info.calendar_id) == calendar_id_norm:
                    return info
        if calendar_id_path:
            for info in calendars:
                if normalize_calendar_path(info.calendar_id) == calendar_id_path:
                    return info
        calendar_name_norm = normalize_calendar_name(calendar_name)
        same_name: list[CalendarInfo] = []
        if calendar_name_norm:
            same_name = [
                info for info in calendars if normalize_calendar_name(info.name) == calendar_name_norm
            ]
            if same_name and not calendar_id_raw:
                same_name.sort(key=lambda item: item.calendar_id)
                return same_name[0]

        if calendar_id_raw:
            if len(same_name) > 1:
                raise RuntimeError(
                    f"Managed calendar not found for configured id: {calendar_id_raw}. "
                    "Multiple same-name calendars exist; refusing to auto-select or auto-create duplicate."
                )
            if len(same_name) == 1:
                return same_name[0]

        calendar = self._principal.make_calendar(name=calendar_name)
        created_id = str(calendar.url)
        self._calendar_cache[created_id] = calendar

        refreshed = self.list_calendars()
        created_norm = normalize_calendar_id(created_id)
        created_path = normalize_calendar_path(created_id)
        for info in refreshed:
            if normalize_calendar_id(info.calendar_id) == created_norm:
                return info
            if created_path and normalize_calendar_path(info.calendar_id) == created_path:
                return info

        fallback_name_norm = normalize_calendar_name(calendar_name)
        if fallback_name_norm:
            same_name = [
                info for info in refreshed if normalize_calendar_name(info.name) == fallback_name_norm
            ]
            if same_name:
                same_name.sort(key=lambda item: item.calendar_id)
                return same_name[0]

        return CalendarInfo(
            calendar_id=created_id,
            name=getattr(calendar, "name", calendar_name) or calendar_name,
            url=created_id,
        )
