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

