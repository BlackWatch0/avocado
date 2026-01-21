from unittest.mock import MagicMock

from caldav_sync.nextcloud_caldav_client import ConflictError, SyncItem, SyncResult
from caldav_sync.sync_engine import SyncStateStore, initial_sync, incremental_sync


def test_initial_sync_does_not_use_limit(tmp_path):
    client = MagicMock()
    client.report_sync_collection.return_value = SyncResult(
        new_sync_token="token1",
        changed=[SyncItem(href="https://example.com/event.ics", etag="etag1")],
        deleted=[],
    )
    client.get_ics.return_value = ("etag1", "BEGIN:VCALENDAR\nEND:VCALENDAR")

    store = SyncStateStore(db_path=str(tmp_path / "state.db"))
    events = initial_sync(client, store, "https://example.com/collection/")

    assert len(events) == 1
    _, kwargs = client.report_sync_collection.call_args
    assert kwargs["limit"] is None


def test_incremental_sync_only_fetches_changed(tmp_path):
    client = MagicMock()
    client.report_sync_collection.return_value = SyncResult(
        new_sync_token="token2",
        changed=[
            SyncItem(href="https://example.com/a.ics", etag="etag-a"),
            SyncItem(href="https://example.com/b.ics", etag="etag-b"),
        ],
        deleted=[SyncItem(href="https://example.com/c.ics")],
    )
    client.get_ics.side_effect = [
        ("etag-b", "BEGIN:VCALENDAR\nEND:VCALENDAR"),
    ]

    store = SyncStateStore(db_path=str(tmp_path / "state.db"))
    store.save_state(
        "https://example.com/collection/", "token1", {"https://example.com/a.ics": "etag-a"}
    )

    diff = incremental_sync(client, store, "https://example.com/collection/")

    assert len(diff.changed) == 1
    assert diff.changed[0].href == "https://example.com/b.ics"
    assert diff.deleted == ["https://example.com/c.ics"]
    client.get_ics.assert_called_once_with("https://example.com/b.ics")


def test_incremental_sync_fallback_on_conflict(tmp_path, monkeypatch):
    client = MagicMock()
    client.report_sync_collection.side_effect = ConflictError("invalid")

    store = SyncStateStore(db_path=str(tmp_path / "state.db"))
    store.save_state("https://example.com/collection/", "token1", {})

    called = {"count": 0}

    def fake_initial_sync(client_arg, store_arg, collection_url, max_workers=8, time_window=None):
        called["count"] += 1
        return []

    monkeypatch.setattr("caldav_sync.sync_engine.initial_sync", fake_initial_sync)

    diff = incremental_sync(client, store, "https://example.com/collection/")

    assert called["count"] == 1
    assert diff.changed == []
