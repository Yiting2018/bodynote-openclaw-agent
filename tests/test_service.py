from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bodynote_agent.config import runtime_paths
from bodynote_agent.events import EventRepository
from bodynote_agent.runtime import initialize
from bodynote_agent.service import CheckinService


NOW = datetime(2026, 7, 16, 10, 15, tzinfo=ZoneInfo("Asia/Shanghai"))


class ServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary_directory.name) / "runtime"
        initialize(self.home)
        self.database = runtime_paths(self.home).database
        self.service = CheckinService(self.database)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_idempotent_text_record(self) -> None:
        first = self.service.record_text(
            "今天走了8000步",
            idempotency_key="message-1",
            now=NOW,
        )
        second = self.service.record_text(
            "今天走了8000步",
            idempotency_key="message-1",
            now=NOW,
        )

        self.assertTrue(first["recorded"])
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["event"]["id"], second["event"]["id"])
        self.assertEqual(self.service.list_events()["count"], 1)
        self.assertEqual(EventRepository(self.database).audit_count(target_id=first["event"]["id"]), 2)

    def test_missing_meal_type_is_saved_with_lower_confidence(self) -> None:
        result = self.service.record_text("今天吃了米饭和鸡胸肉", now=NOW)
        self.assertTrue(result["recorded"])
        self.assertEqual(result["event"]["payload"]["meal_type"], "unspecified")
        self.assertIsNotNone(result["follow_up_question"])
        self.assertIn("meal_type_missing", result["warnings"])

    def test_invalid_body_value_is_rejected(self) -> None:
        result = self.service.record_text("今天体重900公斤", now=NOW)
        self.assertFalse(result["ok"])
        self.assertFalse(result["recorded"])
        self.assertEqual(self.service.list_events()["count"], 0)

    def test_update_increments_revision_and_merges_payload(self) -> None:
        created = self.service.record_text("今天走了8000步", now=NOW)
        event_id = created["event"]["id"]

        updated = self.service.update_event(
            event_id,
            {"payload": {"steps": 9200}, "raw_text": "修正：今天走了9200步"},
        )

        self.assertTrue(updated["updated"])
        self.assertEqual(updated["event"]["payload"]["steps"], 9200)
        self.assertEqual(updated["event"]["revision"], 2)
        self.assertIn("修正", updated["event"]["raw_text"])

    def test_soft_delete_hides_event(self) -> None:
        created = self.service.record_text("今早体重61.2kg", now=NOW)
        event_id = created["event"]["id"]

        deleted = self.service.delete_event(event_id)

        self.assertTrue(deleted["deleted"])
        self.assertEqual(self.service.list_events()["count"], 0)
        history = self.service.list_events(include_deleted=True)
        self.assertEqual(history["count"], 1)
        self.assertIsNotNone(history["events"][0]["deleted_at"])
        self.assertEqual(history["events"][0]["revision"], 2)

    def test_urgent_symptom_returns_safety_message(self) -> None:
        result = self.service.record_text("突然胸痛，程度7分", now=NOW)
        self.assertTrue(result["recorded"])
        self.assertEqual(result["safety"]["level"], "urgent")

    def test_structured_record(self) -> None:
        result = self.service.record_structured(
            {
                "event_type": "blood_glucose",
                "occurred_at": "2026-07-16T08:00:00+08:00",
                "payload": {"glucose_mmol_l": 5.6, "context": "fasting"},
                "idempotency_key": "glucose-1",
                "confidence": 0.99,
            }
        )
        self.assertTrue(result["recorded"])
        self.assertEqual(result["event"]["payload"]["glucose_mmol_l"], 5.6)

    def test_structured_record_requires_timezone(self) -> None:
        result = self.service.record_structured(
            {
                "event_type": "body",
                "occurred_at": "2026-07-16T08:00:00",
                "payload": {"weight_kg": 61.2},
            }
        )
        self.assertFalse(result["recorded"])
        self.assertIn("时区", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
