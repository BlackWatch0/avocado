from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from avocado.persistence.state_store.schema import utc_now


class AuditRepoMixin:
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
                    (run_id, utc_now(), calendar_id, uid, action, json.dumps(details, ensure_ascii=False)),
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
