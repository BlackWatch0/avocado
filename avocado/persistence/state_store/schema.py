from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    duration_ms INTEGER NOT NULL,
    changes_applied INTEGER NOT NULL,
    conflicts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    created_at TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    uid TEXT NOT NULL,
    action TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_snapshots (
    calendar_id TEXT NOT NULL,
    uid TEXT NOT NULL,
    etag TEXT,
    payload_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (calendar_id, uid)
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_tokens (
    source_key TEXT PRIMARY KEY,
    sync_token TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_mappings (
    sync_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_calendar_id TEXT NOT NULL,
    source_uid TEXT NOT NULL,
    source_href_hash TEXT NOT NULL,
    user_uid TEXT NOT NULL,
    stack_uid TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_event_mappings_source_uid
    ON event_mappings(source, source_calendar_id, source_uid);
CREATE INDEX IF NOT EXISTS idx_event_mappings_user_uid
    ON event_mappings(user_uid);
CREATE INDEX IF NOT EXISTS idx_event_mappings_stack_uid
    ON event_mappings(stack_uid);

CREATE TABLE IF NOT EXISTS suppression_tombstones (
    source TEXT NOT NULL,
    source_calendar_id TEXT NOT NULL,
    source_uid TEXT NOT NULL,
    reason TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (source, source_calendar_id, source_uid)
);

CREATE TABLE IF NOT EXISTS pending_new_cleanup (
    new_uid TEXT PRIMARY KEY,
    new_href TEXT NOT NULL,
    mapped_sync_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class SchemaMixin:
    def _init_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.executescript(SCHEMA_SQL)
