from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict, is_dataclass
from datetime import date, datetime

from caldav_sync.ai_tag_parser import parse_ai_block
from caldav_sync.ics_parser import parse_ics_events
from caldav_sync.mapper import map_event
from caldav_sync.nextcloud_caldav_client import NextcloudCalDAVClient
from caldav_sync.sync_engine import SyncStateStore, incremental_sync

logging.basicConfig(level=logging.INFO)


def main() -> None:
    parser = argparse.ArgumentParser(description="Nextcloud CalDAV incremental sync")
    parser.add_argument("sync", nargs="?", default="sync")
    parser.add_argument("--collection", required=True, help="CalDAV collection URL")
    parser.add_argument("--base-url", default=os.getenv("NEXTCLOUD_BASE", ""))
    parser.add_argument("--user", default=os.getenv("NEXTCLOUD_USER", ""))
    parser.add_argument("--password", default=os.getenv("NEXTCLOUD_PASS", ""))
    parser.add_argument("--db", default="sync_state.db")
    args = parser.parse_args()

    if not args.base_url or not args.user or not args.password:
        raise SystemExit("Missing NEXTCLOUD_BASE/NEXTCLOUD_USER/NEXTCLOUD_PASS")

    client = NextcloudCalDAVClient(
        base_url=args.base_url,
        username=args.user,
        password=args.password,
    )
    store = SyncStateStore(db_path=args.db)
    diff = incremental_sync(client, store, args.collection)

    output = []
    for raw in diff.changed:
        events = parse_ics_events(raw.ics_text)
        for event in events:
            event = event.__class__(
                **{
                    **asdict(event),
                    "href": raw.href,
                    "etag": raw.etag,
                    "collection_url": raw.collection_url,
                }
            )
            ai_meta = parse_ai_block(event.description)
            mapped = map_event(event, ai_meta)
            output.append(mapped)

    print(
        json.dumps(
            {
                "changed": len(diff.changed),
                "deleted": len(diff.deleted),
                "items": [serialize(item) for item in output],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def serialize(obj):
    if is_dataclass(obj):
        return {k: serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


if __name__ == "__main__":
    main()
