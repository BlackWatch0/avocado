from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        schema_sql = """
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
        with self._lock:
            with self._connect() as conn:
                conn.executescript(schema_sql)

    def record_sync_run(
        self,
        *,
        trigger: str,
        status: str,
        message: str,
        duration_ms: int,
        changes_applied: int,
        conflicts: int,
    ) -> int:
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO sync_runs(run_at, trigger, status, message, duration_ms, changes_applied, conflicts)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (_utc_now(), trigger, status, message, duration_ms, changes_applied, conflicts),
                )
                conn.commit()
                return int(cursor.lastrowid)

    def start_sync_run(self, *, trigger: str, message: str = "running") -> int:
        return self.record_sync_run(
            trigger=trigger,
            status="running",
            message=message,
            duration_ms=0,
            changes_applied=0,
            conflicts=0,
        )

    def finish_sync_run(
        self,
        *,
        run_id: int,
        status: str,
        message: str,
        duration_ms: int,
        changes_applied: int,
        conflicts: int,
    ) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE sync_runs
                    SET status = ?, message = ?, duration_ms = ?, changes_applied = ?, conflicts = ?
                    WHERE id = ?
                    """,
                    (
                        str(status),
                        str(message),
                        int(duration_ms),
                        int(changes_applied),
                        int(conflicts),
                        int(run_id),
                    ),
                )
                conn.commit()

    def recent_sync_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, run_at, trigger, status, message, duration_ms, changes_applied, conflicts
                    FROM sync_runs
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (max(1, limit),),
                ).fetchall()
        return [dict(row) for row in rows]

    def record_audit_event(
        self,
        *,
        calendar_id: str,
        uid: str,
        action: str,
        details: dict[str, Any],
        run_id: int | None = None,
    ) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_events(run_id, created_at, calendar_id, uid, action, details_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, _utc_now(), calendar_id, uid, action, json.dumps(details, ensure_ascii=False)),
                )
                conn.commit()

    def recent_audit_events(self, limit: int = 100, run_id: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                if run_id is None:
                    rows = conn.execute(
                        """
                        SELECT id, run_id, created_at, calendar_id, uid, action, details_json
                        FROM audit_events
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (max(1, limit),),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT id, run_id, created_at, calendar_id, uid, action, details_json
                        FROM audit_events
                        WHERE run_id = ?
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (int(run_id), max(1, limit)),
                    ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json") or "{}")
            output.append(item)
        return output

    def get_audit_event(self, event_id: int) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT id, run_id, created_at, calendar_id, uid, action, details_json
                    FROM audit_events
                    WHERE id = ?
                    """,
                    (int(event_id),),
                ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["details"] = json.loads(item.pop("details_json") or "{}")
        return item

    def upsert_snapshot(
        self,
        *,
        calendar_id: str,
        uid: str,
        etag: str,
        payload_hash: str,
    ) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO event_snapshots(calendar_id, uid, etag, payload_hash, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(calendar_id, uid) DO UPDATE SET
                        etag = excluded.etag,
                        payload_hash = excluded.payload_hash,
                        updated_at = excluded.updated_at
                    """,
                    (calendar_id, uid, etag, payload_hash, _utc_now()),
                )
                conn.commit()

    def get_snapshot(self, calendar_id: str, uid: str) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT calendar_id, uid, etag, payload_hash, updated_at
                    FROM event_snapshots
                    WHERE calendar_id = ? AND uid = ?
                    """,
                    (calendar_id, uid),
                ).fetchone()
        return dict(row) if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO app_meta(key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (str(key), str(value), _utc_now()),
                )
                conn.commit()

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT value
                    FROM app_meta
                    WHERE key = ?
                    """,
                    (str(key),),
                ).fetchone()
        if row is None:
            return None
        return str(row["value"])

    def set_sync_token(self, *, source_key: str, sync_token: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sync_tokens(source_key, sync_token, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(source_key) DO UPDATE SET
                        sync_token = excluded.sync_token,
                        updated_at = excluded.updated_at
                    """,
                    (str(source_key), str(sync_token), _utc_now()),
                )
                conn.commit()

    def get_sync_token(self, *, source_key: str) -> str | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT sync_token
                    FROM sync_tokens
                    WHERE source_key = ?
                    """,
                    (str(source_key),),
                ).fetchone()
        if row is None:
            return None
        return str(row["sync_token"])

    def list_sync_tokens(self) -> dict[str, str]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT source_key, sync_token
                    FROM sync_tokens
                    """
                ).fetchall()
        return {str(row["source_key"]): str(row["sync_token"]) for row in rows}

    def upsert_event_mapping(
        self,
        *,
        sync_id: str,
        source: str,
        source_calendar_id: str,
        source_uid: str,
        source_href_hash: str,
        user_uid: str,
        stack_uid: str,
        status: str = "active",
    ) -> None:
        now = _utc_now()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO event_mappings(
                        sync_id,
                        source,
                        source_calendar_id,
                        source_uid,
                        source_href_hash,
                        user_uid,
                        stack_uid,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sync_id) DO UPDATE SET
                        source = excluded.source,
                        source_calendar_id = excluded.source_calendar_id,
                        source_uid = excluded.source_uid,
                        source_href_hash = excluded.source_href_hash,
                        user_uid = excluded.user_uid,
                        stack_uid = excluded.stack_uid,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        str(sync_id),
                        str(source),
                        str(source_calendar_id),
                        str(source_uid),
                        str(source_href_hash),
                        str(user_uid),
                        str(stack_uid),
                        str(status),
                        now,
                        now,
                    ),
                )
                conn.commit()

    def _get_event_mapping_row(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def get_event_mapping_by_sync_id(self, sync_id: str) -> dict[str, Any] | None:
        return self._get_event_mapping_row(
            """
            SELECT *
            FROM event_mappings
            WHERE sync_id = ?
            """,
            (str(sync_id),),
        )

    def get_event_mapping_by_source(
        self, *, source: str, source_calendar_id: str, source_uid: str
    ) -> dict[str, Any] | None:
        return self._get_event_mapping_row(
            """
            SELECT *
            FROM event_mappings
            WHERE source = ? AND source_calendar_id = ? AND source_uid = ?
            """,
            (str(source), str(source_calendar_id), str(source_uid)),
        )

    def get_event_mapping_by_user_uid(self, user_uid: str) -> dict[str, Any] | None:
        return self._get_event_mapping_row(
            """
            SELECT *
            FROM event_mappings
            WHERE user_uid = ?
            """,
            (str(user_uid),),
        )

    def get_event_mapping_by_stack_uid(self, stack_uid: str) -> dict[str, Any] | None:
        return self._get_event_mapping_row(
            """
            SELECT *
            FROM event_mappings
            WHERE stack_uid = ?
            """,
            (str(stack_uid),),
        )

    def list_event_mappings(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM event_mappings
                    """
                ).fetchall()
        return [dict(row) for row in rows]

    def set_event_mapping_status(self, *, sync_id: str, status: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE event_mappings
                    SET status = ?, updated_at = ?
                    WHERE sync_id = ?
                    """,
                    (str(status), _utc_now(), str(sync_id)),
                )
                conn.commit()

    def upsert_suppression_tombstone(
        self,
        *,
        source: str,
        source_calendar_id: str,
        source_uid: str,
        reason: str,
        expires_at: str,
    ) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO suppression_tombstones(
                        source,
                        source_calendar_id,
                        source_uid,
                        reason,
                        expires_at,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source, source_calendar_id, source_uid) DO UPDATE SET
                        reason = excluded.reason,
                        expires_at = excluded.expires_at
                    """,
                    (
                        str(source),
                        str(source_calendar_id),
                        str(source_uid),
                        str(reason),
                        str(expires_at),
                        _utc_now(),
                    ),
                )
                conn.commit()

    def get_suppression_tombstone(
        self, *, source: str, source_calendar_id: str, source_uid: str
    ) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT *
                    FROM suppression_tombstones
                    WHERE source = ? AND source_calendar_id = ? AND source_uid = ?
                    """,
                    (str(source), str(source_calendar_id), str(source_uid)),
                ).fetchone()
        return dict(row) if row else None

    def list_active_suppression_tombstones(self, *, now_iso: str) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM suppression_tombstones
                    WHERE expires_at > ?
                    """,
                    (str(now_iso),),
                ).fetchall()
        return [dict(row) for row in rows]

    def delete_suppression_tombstone(
        self, *, source: str, source_calendar_id: str, source_uid: str
    ) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    DELETE FROM suppression_tombstones
                    WHERE source = ? AND source_calendar_id = ? AND source_uid = ?
                    """,
                    (str(source), str(source_calendar_id), str(source_uid)),
                )
                conn.commit()

    def enqueue_pending_new_cleanup(self, *, new_uid: str, new_href: str, mapped_sync_id: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO pending_new_cleanup(new_uid, new_href, mapped_sync_id, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(new_uid) DO UPDATE SET
                        new_href = excluded.new_href,
                        mapped_sync_id = excluded.mapped_sync_id
                    """,
                    (str(new_uid), str(new_href), str(mapped_sync_id), _utc_now()),
                )
                conn.commit()

    def list_pending_new_cleanup(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM pending_new_cleanup
                    ORDER BY created_at ASC
                    """
                ).fetchall()
        return [dict(row) for row in rows]

    def dequeue_pending_new_cleanup(self, *, new_uid: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    DELETE FROM pending_new_cleanup
                    WHERE new_uid = ?
                    """,
                    (str(new_uid),),
                )
                conn.commit()

    def ai_request_bytes_series(self, *, days: int = 90, limit: int = 5000) -> list[dict[str, Any]]:
        days = max(1, int(days))
        limit = max(1, int(limit))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, created_at, details_json
                    FROM audit_events
                    WHERE action = 'ai_request'
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        points: list[dict[str, Any]] = []
        for row in reversed(rows):
            created_at = str(row["created_at"] or "")
            try:
                created_dt = datetime.fromisoformat(created_at)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if created_dt < cutoff:
                continue
            try:
                details = json.loads(row["details_json"] or "{}")
            except Exception:
                details = {}
            request_bytes = int(details.get("request_bytes", 0) or 0)
            if request_bytes <= 0:
                continue
            points.append(
                {
                    "id": int(row["id"]),
                    "created_at": created_at,
                    "request_bytes": request_bytes,
                }
            )
        return points

