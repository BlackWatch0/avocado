from __future__ import annotations

from avocado.persistence.state_store.schema import utc_now


class MetaRepoMixin:
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
                    (str(key), str(value), utc_now()),
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
                    (str(source_key), str(sync_token), utc_now()),
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
