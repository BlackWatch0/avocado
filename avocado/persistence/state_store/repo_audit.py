from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from avocado.persistence.state_store.schema import utc_now


class AuditRepoMixin:
    @staticmethod
    def _extract_total_tokens(details: dict[str, Any]) -> int:
        prompt_tokens = int(details.get("prompt_tokens", 0) or 0)
        completion_tokens = int(details.get("completion_tokens", 0) or 0)
        total_tokens = int(details.get("total_tokens", 0) or 0)
        if total_tokens <= 0:
            total_tokens = max(0, prompt_tokens) + max(0, completion_tokens)
        return max(0, total_tokens)

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
                run_rows = conn.execute(
                    """
                    SELECT id, run_at, status, trigger
                    FROM sync_runs
                    WHERE status != 'running'
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                run_ids = [int(row["id"]) for row in run_rows]
                ai_rows = []
                if run_ids:
                    placeholders = ",".join(["?"] * len(run_ids))
                    ai_rows = conn.execute(
                        f"""
                        SELECT run_id, details_json
                        FROM audit_events
                        WHERE action = 'ai_request'
                          AND run_id IN ({placeholders})
                        """,
                        tuple(run_ids),
                    ).fetchall()
        tokens_by_run: dict[int, dict[str, int]] = {}
        flex_by_run: dict[int, bool] = {}
        for row in ai_rows:
            run_id = int(row["run_id"])
            try:
                details = json.loads(row["details_json"] or "{}")
            except Exception:
                details = {}
            total_tokens = self._extract_total_tokens(details if isinstance(details, dict) else {})
            prompt_tokens = int((details or {}).get("prompt_tokens", 0) or 0)
            completion_tokens = int((details or {}).get("completion_tokens", 0) or 0)
            service_tier = str((details or {}).get("service_tier", "") or "").strip().lower()
            agg = tokens_by_run.setdefault(
                run_id,
                {"request_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0},
            )
            agg["request_tokens"] += max(0, total_tokens)
            agg["prompt_tokens"] += max(0, prompt_tokens)
            agg["completion_tokens"] += max(0, completion_tokens)
            if service_tier == "flex":
                flex_by_run[run_id] = True
        points: list[dict[str, Any]] = []
        for row in reversed(run_rows):
            created_at = str(row["run_at"] or "")
            try:
                created_dt = datetime.fromisoformat(created_at)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if created_dt < cutoff:
                continue
            run_id = int(row["id"])
            agg = tokens_by_run.get(
                run_id,
                {"request_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0},
            )
            points.append(
                {
                    "id": run_id,
                    "created_at": created_at,
                    "request_tokens": int(agg.get("request_tokens", 0) or 0),
                    "prompt_tokens": int(agg.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(agg.get("completion_tokens", 0) or 0),
                    "flex_used": bool(flex_by_run.get(run_id, False)),
                    "sync_status": str(row["status"] or ""),
                    "trigger": str(row["trigger"] or ""),
                }
            )
        return points
