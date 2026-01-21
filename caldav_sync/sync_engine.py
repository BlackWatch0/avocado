from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from caldav_sync.nextcloud_caldav_client import (
    ConflictError,
    NextcloudCalDAVClient,
    SyncResult,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawEvent:
    collection_url: str
    href: str
    etag: Optional[str]
    ics_text: str


@dataclass(frozen=True)
class SyncDiff:
    changed: list[RawEvent]
    deleted: list[str]
    new_sync_token: str


class SyncStateStore:
    def __init__(self, db_path: str = "sync_state.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_state (
                    collection_url TEXT PRIMARY KEY,
                    sync_token TEXT,
                    href_etag_map TEXT
                )
                """
            )
            conn.commit()

    def get_state(self, collection_url: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT sync_token, href_etag_map FROM sync_state WHERE collection_url = ?",
                (collection_url,),
            )
            row = cursor.fetchone()
        if not row:
            return {"sync_token": None, "href_etag_map": {}}
        sync_token, href_etag_map = row
        return {
            "sync_token": sync_token,
            "href_etag_map": json.loads(href_etag_map) if href_etag_map else {},
        }

    def save_state(self, collection_url: str, sync_token: str, href_etag_map: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO sync_state (collection_url, sync_token, href_etag_map)
                VALUES (?, ?, ?)
                ON CONFLICT(collection_url) DO UPDATE SET
                    sync_token = excluded.sync_token,
                    href_etag_map = excluded.href_etag_map
                """,
                (collection_url, sync_token, json.dumps(href_etag_map)),
            )
            conn.commit()


def initial_sync(
    client: NextcloudCalDAVClient,
    store: SyncStateStore,
    collection_url: str,
    time_window: Optional[tuple[str, str]] = None,
    max_workers: int = 8,
) -> list[RawEvent]:
    logger.info("Initial sync for %s", collection_url)
    if time_window:
        logger.debug("Time window provided but not enforced: %s", time_window)
    sync_result = client.report_sync_collection(
        collection_url, sync_token=None, include_etag=True, limit=None
    )
    events = _fetch_changed_events(
        client, collection_url, sync_result, {}, max_workers=max_workers
    )
    href_etag_map = {event.href: event.etag for event in events if event.etag}
    store.save_state(collection_url, sync_result.new_sync_token, href_etag_map)
    return events


def incremental_sync(
    client: NextcloudCalDAVClient,
    store: SyncStateStore,
    collection_url: str,
    max_workers: int = 8,
) -> SyncDiff:
    state = store.get_state(collection_url)
    sync_token = state["sync_token"]
    href_etag_map: dict[str, str] = state["href_etag_map"]
    token_hint = _hash_token(sync_token)
    logger.info("Incremental sync for %s (token=%s)", collection_url, token_hint)
    try:
        sync_result = client.report_sync_collection(
            collection_url,
            sync_token=sync_token,
            include_etag=True,
        )
    except ConflictError:
        logger.warning("Sync token invalid, falling back to initial sync.")
        events = initial_sync(client, store, collection_url, max_workers=max_workers)
        return SyncDiff(changed=events, deleted=[], new_sync_token=store.get_state(collection_url)["sync_token"])

    changed_events = _fetch_changed_events(
        client, collection_url, sync_result, href_etag_map, max_workers=max_workers
    )
    deleted_hrefs = [item.href for item in sync_result.deleted]

    for event in changed_events:
        if event.etag:
            href_etag_map[event.href] = event.etag
    for href in deleted_hrefs:
        href_etag_map.pop(href, None)

    store.save_state(collection_url, sync_result.new_sync_token, href_etag_map)
    return SyncDiff(
        changed=changed_events,
        deleted=deleted_hrefs,
        new_sync_token=sync_result.new_sync_token,
    )


def _fetch_changed_events(
    client: NextcloudCalDAVClient,
    collection_url: str,
    sync_result: SyncResult,
    href_etag_map: dict[str, str],
    max_workers: int,
) -> list[RawEvent]:
    events: list[RawEvent] = []
    items = []
    for item in sync_result.changed:
        if item.etag and href_etag_map.get(item.href) == item.etag:
            logger.debug("Skipping unchanged href: %s", item.href)
            continue
        items.append(item)

    if not items:
        return []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(client.get_ics, item.href): item for item in items
        }
        for future in as_completed(future_map):
            item = future_map[future]
            try:
                etag, ics_text = future.result()
            except Exception as exc:  # pragma: no cover - unexpected
                logger.error("Failed to fetch %s: %s", item.href, exc)
                continue
            resolved_etag = etag or item.etag
            events.append(
                RawEvent(
                    collection_url=collection_url,
                    href=item.href,
                    etag=resolved_etag,
                    ics_text=ics_text,
                )
            )
    return events


def _hash_token(token: Optional[str]) -> str:
    if not token:
        return "none"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return digest[:8]
