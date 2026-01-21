from datetime import date, datetime
from zoneinfo import ZoneInfo

from caldav_sync.ics_parser import parse_ics_events


def test_parse_multiple_events_from_fixture():
    ics_text = open("caldav_sync/tests/fixtures/sample.ics", "r", encoding="utf-8").read()
    events = parse_ics_events(ics_text)
    assert len(events) == 3
    assert events[0].uid == "evt-1"
    assert events[1].uid == "evt-2"
    assert events[2].all_day is True


def test_parse_utc_and_tzid():
    ics_text = open("caldav_sync/tests/fixtures/sample.ics", "r", encoding="utf-8").read()
    events = parse_ics_events(ics_text)
    utc_event = events[0]
    assert isinstance(utc_event.start, datetime)
    assert utc_event.start.tzinfo == ZoneInfo("UTC")
    tz_event = events[1]
    assert tz_event.start.tzinfo == ZoneInfo("Europe/London")


def test_parse_value_date_all_day():
    ics_text = open("caldav_sync/tests/fixtures/sample.ics", "r", encoding="utf-8").read()
    events = parse_ics_events(ics_text)
    all_day_event = events[2]
    assert all_day_event.all_day is True
    assert isinstance(all_day_event.start, date)


def test_description_unescape():
    ics_text = open("caldav_sync/tests/fixtures/sample.ics", "r", encoding="utf-8").read()
    events = parse_ics_events(ics_text)
    description = events[0].description
    assert "Line1" in description
    assert "Line2" in description
