from __future__ import annotations


from avocado.persistence.state_store.schema import utc_now


class NewCleanupRepoMixin:
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
                    (str(new_uid), str(new_href), str(mapped_sync_id), utc_now()),
                )
                conn.commit()

    def list_pending_new_cleanup(self) -> list[dict[str, object]]:
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
