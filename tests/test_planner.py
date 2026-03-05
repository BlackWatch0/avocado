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
                    "all_day": True,
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
            current_time="2026-03-04T08:00:00+00:00",
        )
        self.assertNotIn("events", payload)
        self.assertEqual(payload["target_uids"], ["avo-001"])
        self.assertEqual(payload.get("current_time"), "2026-03-04T08:00:00+00:00")
        events_by_uid = payload.get("events_by_uid", {})
        self.assertIn("avo-001", events_by_uid)
        item = events_by_uid["avo-001"]
        self.assertEqual(item.get("time_range"), ["2026-03-04T09:00:00+00:00", "2026-03-04T10:00:00+00:00"])
        self.assertEqual(item.get("summary"), "Deep Work")
        self.assertEqual(item.get("locked"), False)
        self.assertIn("location", item)
        self.assertIn("description", item)
        self.assertIn("all_day", item)
        self.assertEqual(item.get("detail_level"), "full")
        self.assertIn("user_intent", item)
        self.assertEqual(item.get("location"), "")
        self.assertTrue(bool(item.get("all_day")))
        self.assertEqual(item.get("user_intent"), "Push by 30 minutes")
        self.assertNotIn("x_sync_id", item)
        self.assertNotIn("etag", item)
        self.assertNotIn("href", item)

    def test_build_planning_payload_sparse_other_events(self) -> None:
        payload = build_planning_payload(
            events=None,
            events_payload=[
                {
                    "uid": "avo-target",
                    "start": "2026-03-04T09:00:00+00:00",
                    "end": "2026-03-04T10:00:00+00:00",
                    "summary": "Target",
                    "location": "Room 1",
                    "description": "Target description",
                    "all_day": False,
                    "locked": False,
                    "user_intent": "move later",
                },
                {
                    "uid": "avo-busy",
                    "start": "2026-03-04T11:00:00+00:00",
                    "end": "2026-03-04T12:00:00+00:00",
                    "summary": "Busy block",
                    "location": "Room 2",
                    "description": "Should be hidden in sparse",
                    "all_day": False,
                    "locked": False,
                },
            ],
            window_start="2026-03-04T00:00:00+00:00",
            window_end="2026-03-05T00:00:00+00:00",
            timezone="UTC",
            target_uids=["avo-target"],
            compact=True,
            sparse_other_events=True,
            full_detail_uids=["avo-target"],
            planning_phase="phase1",
            target_description_max_chars=10,
            neighbor_description_max_chars=5,
        )
        events_by_uid = payload.get("events_by_uid", {})
        self.assertEqual(payload.get("planning_phase"), "phase1")
        target_item = events_by_uid.get("avo-target", {})
        self.assertEqual(target_item.get("detail_level"), "full")
        self.assertIn("location", target_item)
        self.assertIn("description", target_item)
        self.assertEqual(target_item.get("description"), "Target des")
        self.assertIn("user_intent", target_item)
        busy_item = events_by_uid.get("avo-busy", {})
        self.assertEqual(busy_item.get("detail_level"), "busy")
        self.assertNotIn("location", busy_item)
        self.assertNotIn("description", busy_item)
        self.assertNotIn("user_intent", busy_item)

    def test_build_planning_payload_uses_neighbor_description_budget(self) -> None:
        payload = build_planning_payload(
            events=None,
            events_payload=[
                {
                    "uid": "avo-target",
                    "start": "2026-03-04T09:00:00+00:00",
                    "end": "2026-03-04T10:00:00+00:00",
                    "summary": "Target",
                    "location": "Room 1",
                    "description": "Long target description",
                    "all_day": False,
                    "locked": False,
                    "user_intent": "move later",
                },
                {
                    "uid": "avo-neighbor",
                    "start": "2026-03-04T10:00:00+00:00",
                    "end": "2026-03-04T11:00:00+00:00",
                    "summary": "Neighbor",
                    "location": "Room 2",
                    "description": "Neighbor description",
                    "all_day": False,
                    "locked": False,
                },
            ],
            window_start="2026-03-04T00:00:00+00:00",
            window_end="2026-03-05T00:00:00+00:00",
            timezone="UTC",
            target_uids=["avo-target"],
            compact=True,
            sparse_other_events=True,
            full_detail_uids=["avo-target", "avo-neighbor"],
            target_description_max_chars=100,
            neighbor_description_max_chars=8,
        )
        events_by_uid = payload.get("events_by_uid", {})
        neighbor_item = events_by_uid.get("avo-neighbor", {})
        self.assertEqual(neighbor_item.get("detail_level"), "full")
        self.assertEqual(neighbor_item.get("description"), "Neighbor")
        self.assertNotIn("user_intent", neighbor_item)

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
                "context_requests": [
                    {"date": "2026-03-10", "reason": "need details"},
                    {"start": "2026-03-11T00:00:00+00:00", "end": "2026-03-12T00:00:00+00:00"},
                ],
            }
        )
        self.assertEqual(len(result["changes"]), 1)
        self.assertEqual(result["changes"][0]["uid"], "avo-001")
        self.assertNotIn("calendar_id", result["changes"][0])
        self.assertEqual(len(result["creates"]), 1)
        self.assertEqual(result["creates"][0]["from_uid"], "avo-001")
        self.assertEqual(result["creates"][0]["create_key"], "split-2")
        self.assertEqual(len(result.get("context_requests", [])), 2)


if __name__ == "__main__":
    unittest.main()
