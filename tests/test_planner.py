from __future__ import annotations

import unittest

from avocado.planner import build_planning_payload, normalize_ai_plan_result


class PlannerTests(unittest.TestCase):
    def test_build_planning_payload_compact_schema(self) -> None:
        payload = build_planning_payload(
            events=None,
            events_payload=[
                {
                    "calendar_id": "stack-cal",
                    "uid": "avo-001",
                    "start": "2026-03-04T09:00:00+00:00",
                    "end": "2026-03-04T10:00:00+00:00",
                    "summary": "Deep Work",
                    "description": "Focus task",
                    "location": "",
                    "locked": False,
                    "etag": "etag-1",
                    "href": "stack-cal/avo-001.ics",
                    "x_sync_id": "sync-1",
                    "x_source": "new",
                    "x_source_uid": "new-1",
                    "user_intent": "Push by 30 minutes",
                }
            ],
            window_start="2026-03-04T00:00:00+00:00",
            window_end="2026-03-05T00:00:00+00:00",
            timezone="UTC",
            target_uids=["avo-001"],
            compact=True,
        )
        self.assertNotIn("events", payload)
        self.assertEqual(payload["target_uids"], ["avo-001"])
        events_by_uid = payload.get("events_by_uid", {})
        self.assertIn("avo-001", events_by_uid)
        item = events_by_uid["avo-001"]
        self.assertEqual(item.get("t"), ["2026-03-04T09:00:00+00:00", "2026-03-04T10:00:00+00:00"])
        self.assertEqual(item.get("s"), "Deep Work")
        self.assertEqual(item.get("k"), False)
        self.assertEqual(item.get("i"), "Push by 30 minutes")
        self.assertNotIn("x_sync_id", item)
        self.assertNotIn("etag", item)
        self.assertNotIn("href", item)

    def test_normalize_ai_plan_result_supports_changes_and_creates(self) -> None:
        result = normalize_ai_plan_result(
            {
                "changes": [
                    {
                        "uid": "avo-001",
                        "start": "2026-03-04T10:00:00+00:00",
                        "end": "2026-03-04T11:00:00+00:00",
                        "reason": "move to avoid overlap",
                    }
                ],
                "creates": [
                    {
                        "from_uid": "avo-001",
                        "create_key": "split-2",
                        "start": "2026-03-04T15:00:00+00:00",
                        "end": "2026-03-04T16:00:00+00:00",
                        "summary": "Deep Work (2/2)",
                        "reason": "split long task",
                    }
                ],
            }
        )
        self.assertEqual(len(result["changes"]), 1)
        self.assertEqual(result["changes"][0]["uid"], "avo-001")
        self.assertNotIn("calendar_id", result["changes"][0])
        self.assertEqual(len(result["creates"]), 1)
        self.assertEqual(result["creates"][0]["from_uid"], "avo-001")
        self.assertEqual(result["creates"][0]["create_key"], "split-2")


if __name__ == "__main__":
    unittest.main()
