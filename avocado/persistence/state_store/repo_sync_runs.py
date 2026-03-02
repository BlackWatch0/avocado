from __future__ import annotations

from typing import Any

from avocado.persistence.state_store.schema import utc_now


class SyncRunsRepoMixin:
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
                    (utc_now(), trigger, status, message, duration_ms, changes_applied, conflicts),
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
