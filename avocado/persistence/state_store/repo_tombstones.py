from __future__ import annotations


from avocado.persistence.state_store.schema import utc_now


class TombstonesRepoMixin:
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
                        utc_now(),
                    ),
                )
                conn.commit()

    def get_suppression_tombstone(
        self, *, source: str, source_calendar_id: str, source_uid: str
    ) -> dict[str, object] | None:
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

    def list_active_suppression_tombstones(self, *, now_iso: str) -> list[dict[str, object]]:
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
