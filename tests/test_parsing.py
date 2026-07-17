from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from bodynote_agent.parsing import ParseError, parse_checkin_text


NOW = datetime(2026, 7, 16, 10, 15, tzinfo=ZoneInfo("Asia/Shanghai"))


class ParsingTest(unittest.TestCase):
    def test_steps(self) -> None:
        result = parse_checkin_text("今天走了8000步", now=NOW)
        self.assertEqual(result.event_type, "exercise")
        self.assertEqual(result.payload["activity"], "walking")
        self.assertEqual(result.payload["steps"], 8000)
        self.assertEqual(result.occurred_at, "2026-07-16T10:15:00+08:00")

    def test_meal_with_relative_time(self) -> None:
        result = parse_checkin_text("昨天午饭吃了米饭、鸡胸肉和青菜", now=NOW)
        self.assertEqual(result.event_type, "meal")
        self.assertEqual(result.payload["meal_type"], "lunch")
        self.assertEqual(result.payload["foods"], ["米饭", "鸡胸肉", "青菜"])
        self.assertEqual(result.occurred_at, "2026-07-15T12:30:00+08:00")

    def test_meal_without_type_requests_optional_follow_up(self) -> None:
        result = parse_checkin_text("今天吃了米饭和鸡胸肉", now=NOW)
        self.assertEqual(result.event_type, "meal")
        self.assertIsNotNone(result.follow_up_question)

    def test_blood_pressure_and_heart_rate(self) -> None:
        result = parse_checkin_text("血压132/86 心率72", now=NOW)
        self.assertEqual(result.event_type, "blood_pressure")
        self.assertEqual(result.payload["systolic"], 132)
        self.assertEqual(result.payload["diastolic"], 86)
        self.assertEqual(result.payload["heart_rate_bpm"], 72)

    def test_sleep(self) -> None:
        result = parse_checkin_text("昨晚睡了7.5小时，质量一般", now=NOW)
        self.assertEqual(result.event_type, "sleep")
        self.assertEqual(result.payload["duration_hours"], 7.5)
        self.assertEqual(result.payload["quality"], "fair")
        self.assertEqual(result.occurred_at, "2026-07-15T19:00:00+08:00")

    def test_body_weight_converts_jin(self) -> None:
        result = parse_checkin_text("今早体重122.4斤", now=NOW)
        self.assertEqual(result.event_type, "body")
        self.assertEqual(result.payload["weight_kg"], 61.2)

    def test_mood(self) -> None:
        result = parse_checkin_text("今天有点焦虑，强度8分", now=NOW)
        self.assertEqual(result.event_type, "mood")
        self.assertEqual(result.payload["mood"], "anxious")
        self.assertEqual(result.payload["intensity"], 8)

    def test_urgent_symptom(self) -> None:
        result = parse_checkin_text("今天突然胸痛，程度7分", now=NOW)
        self.assertEqual(result.event_type, "symptom")
        self.assertIn("chest_pain", result.payload["symptom"])
        self.assertIn("urgent_symptom", result.warnings)

    def test_unrecognized_text(self) -> None:
        with self.assertRaises(ParseError):
            parse_checkin_text("帮我看看今天怎么样", now=NOW)

    def test_health_question_is_not_saved_as_meal(self) -> None:
        with self.assertRaises(ParseError):
            parse_checkin_text("午饭应该吃什么？", now=NOW)

    def test_self_harm_text_is_urgent_mood_event(self) -> None:
        result = parse_checkin_text("我有点不想活", now=NOW)
        self.assertEqual(result.event_type, "mood")
        self.assertEqual(result.payload["mood"], "self_harm_risk")
        self.assertIn("urgent_mental_health", result.warnings)


if __name__ == "__main__":
    unittest.main()
