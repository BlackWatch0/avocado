from __future__ import annotations

from typing import Any

from avocado.persistence.state_store.schema import utc_now


class MappingsRepoMixin:
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
        now = utc_now()
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
                    (str(status), utc_now(), str(sync_id)),
                )
                conn.commit()
