import unittest

from avocado.core.models import CalendarInfo, CalDAVConfig
from avocado.integrations.caldav.service import CalDAVService


class _DummyCreatedCalendar:
    def __init__(self, url: str, name: str) -> None:
        self.url = url
        self.name = name


class _DummyPrincipal:
    def __init__(self) -> None:
        self.created = 0

    def make_calendar(self, name: str):
        self.created += 1
        return _DummyCreatedCalendar(
            url=f"https://example.test/remote.php/dav/calendars/test/created-{self.created}/",
            name=name,
        )


class _DummyCalDAVService(CalDAVService):
    def __init__(self, calendars: list[CalendarInfo]) -> None:
        super().__init__(CalDAVConfig(base_url="https://example.test", username="u", password="p"))
        self._dummy_calendars = list(calendars)
        self._principal = _DummyPrincipal()

    def _connect(self) -> None:
        return

    def list_calendars(self) -> list[CalendarInfo]:
        return list(self._dummy_calendars)


class CalDAVEnsureManagedCalendarTests(unittest.TestCase):
    def test_creates_when_configured_id_missing_and_no_same_name(self) -> None:
        service = _DummyCalDAVService(
            [
                CalendarInfo(
                    calendar_id="https://example.test/remote.php/dav/calendars/test/personal/",
                    name="Personal",
                    url="https://example.test/remote.php/dav/calendars/test/personal/",
                )
            ]
        )
        created = service.ensure_managed_calendar(
            "https://example.test/remote.php/dav/calendars/test/missing-stack/",
            "Avocado AI Staging",
        )
        self.assertIn("created-1", created.calendar_id)
        self.assertEqual(service._principal.created, 1)

    def test_creates_when_id_empty_and_name_missing(self) -> None:
        service = _DummyCalDAVService(
            [
                CalendarInfo(
                    calendar_id="https://example.test/remote.php/dav/calendars/test/personal/",
                    name="Personal",
                    url="https://example.test/remote.php/dav/calendars/test/personal/",
                )
            ]
        )
        created = service.ensure_managed_calendar("", "Avocado AI Staging")
        self.assertIn("created-1", created.calendar_id)
        self.assertEqual(service._principal.created, 1)

    def test_matches_by_name_without_creation(self) -> None:
        service = _DummyCalDAVService(
            [
                CalendarInfo(
                    calendar_id="https://example.test/remote.php/dav/calendars/test/existing-stack/",
                    name="Avocado AI Staging",
                    url="https://example.test/remote.php/dav/calendars/test/existing-stack/",
                )
            ]
        )
        found = service.ensure_managed_calendar("", "Avocado AI Staging")
        self.assertIn("existing-stack", found.calendar_id)
        self.assertEqual(service._principal.created, 0)

    def test_refuses_when_configured_id_missing_and_multiple_same_name(self) -> None:
        service = _DummyCalDAVService(
            [
                CalendarInfo(
                    calendar_id="https://example.test/remote.php/dav/calendars/test/existing-stack-a/",
                    name="Avocado AI Staging",
                    url="https://example.test/remote.php/dav/calendars/test/existing-stack-a/",
                ),
                CalendarInfo(
                    calendar_id="https://example.test/remote.php/dav/calendars/test/existing-stack-b/",
                    name="Avocado AI Staging",
                    url="https://example.test/remote.php/dav/calendars/test/existing-stack-b/",
                ),
            ]
        )
        with self.assertRaises(RuntimeError):
            service.ensure_managed_calendar(
                "https://example.test/remote.php/dav/calendars/test/missing-stack/",
                "Avocado AI Staging",
            )
        self.assertEqual(service._principal.created, 0)


if __name__ == "__main__":
    unittest.main()
