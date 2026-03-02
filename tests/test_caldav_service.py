import unittest
from unittest import mock

from avocado.core.models import CalDAVConfig
from avocado.integrations.caldav.service import CalDAVService


class _FakeCalendar:
    def __init__(self, url: str, name: str = "") -> None:
        self.url = url
        self.name = name


class _FakePrincipal:
    def __init__(self, calendars: list[_FakeCalendar]) -> None:
        self._calendars = calendars
        self.make_calls = 0

    def calendars(self) -> list[_FakeCalendar]:
        return list(self._calendars)

    def make_calendar(self, name: str) -> _FakeCalendar:
        self.make_calls += 1
        created = _FakeCalendar(
            url=f"https://new-host/remote.php/dav/calendars/test/{name.lower().replace(' ', '-')}/",
            name=name,
        )
        self._calendars.append(created)
        return created


class CalDAVServiceTests(unittest.TestCase):
    def test_ensure_managed_calendar_matches_by_path_not_host(self) -> None:
        existing = _FakeCalendar(
            url="https://internal-host/remote.php/dav/calendars/test/stack-calendar/",
            name="",
        )
        principal = _FakePrincipal([existing])
        service = CalDAVService(CalDAVConfig())
        service._principal = principal  # type: ignore[attr-defined]

        with mock.patch.object(service, "_connect", return_value=None):
            info = service.ensure_managed_calendar(
                "https://public-host/remote.php/dav/calendars/test/stack-calendar/",
                "Avocado Stack Calendar",
            )

        self.assertEqual(info.calendar_id, str(existing.url))
        self.assertEqual(principal.make_calls, 0)

    def test_get_calendar_matches_by_path_not_host(self) -> None:
        existing = _FakeCalendar(
            url="https://internal-host/remote.php/dav/calendars/test/user-calendar/",
            name="User",
        )
        principal = _FakePrincipal([existing])
        service = CalDAVService(CalDAVConfig())
        service._principal = principal  # type: ignore[attr-defined]
        service._calendar_cache = {}  # type: ignore[attr-defined]

        with mock.patch.object(service, "_connect", return_value=None):
            result = service._get_calendar(
                "https://public-host/remote.php/dav/calendars/test/user-calendar/"
            )

        self.assertIs(result, existing)


if __name__ == "__main__":
    unittest.main()
