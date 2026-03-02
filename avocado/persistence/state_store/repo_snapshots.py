from __future__ import annotations

from typing import Any

from avocado.persistence.state_store.schema import utc_now


class SnapshotsRepoMixin:
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
                    (calendar_id, uid, etag, payload_hash, utc_now()),
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
