from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bodynote_agent.parsing import ParseError, parse_checkin_text


NOW = datetime(2026, 7, 16, 10, 15, tzinfo=ZoneInfo("Asia/Shanghai"))


class ParsingTest(unittest.TestCase):
    def test_graywind_real_input_regression_fixture(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "graywind_regressions.json"
        for case in json.loads(fixture.read_text(encoding="utf-8")):
            with self.subTest(text=case["text"]):
                parsed = parse_checkin_text(case["text"], now=datetime.fromisoformat(case["now"]))
                self.assertEqual(parsed.event_type, case["event_type"])
                self.assertEqual(parsed.occurred_at, case["occurred_at"])
                self.assertEqual(parsed.handler, case["handler"])

    def test_handler_contract_exposes_intent_requirements_and_ambiguities(self) -> None:
        parsed = parse_checkin_text("今天吃了米饭和鸡胸肉", now=NOW)
        self.assertEqual(parsed.intent, "record_meal")
        self.assertEqual(parsed.required_fields, ("foods",))
        self.assertIn("meal_type", parsed.ambiguities)

    def test_medical_report_has_dedicated_handler(self) -> None:
        parsed = parse_checkin_text("体检报告有2项异常，复查1项", now=NOW)
        self.assertEqual(parsed.event_type, "medical_report")
        self.assertEqual(parsed.handler, "MedicalReportHandler")
        self.assertEqual(len(parsed.payload["findings"]), 2)

    def test_fuzzy_early_time_is_explicitly_marked(self) -> None:
        parsed = parse_checkin_text("今天很早体重62.5kg", now=NOW)
        self.assertEqual(parsed.occurred_at, "2026-07-16T06:30:00+08:00")
        self.assertIn("fuzzy_occurred_at:early_morning", parsed.ambiguities)
        self.assertIn("fuzzy_time_assumed_06_30", parsed.warnings)
    def test_steps(self) -> None:
        result = parse_checkin_text("今天走了8000步", now=NOW)
        self.assertEqual(result.event_type, "exercise")
        self.assertEqual(result.payload["activity"], "walking")
        self.assertEqual(result.payload["steps"], 8000)
        self.assertEqual(result.occurred_at, "2026-07-16T10:15:00+08:00")
        self.assertEqual(result.handler, "ExerciseHandler")
        self.assertEqual(result.intent_candidates, ("ExerciseHandler",))

    def test_router_exposes_multiple_domain_candidates(self) -> None:
        result = parse_checkin_text("晚饭后跑步30分钟", now=NOW)
        self.assertEqual(result.handler, "ExerciseHandler")
        self.assertIn("MealHandler", result.intent_candidates)
        self.assertIn("multiple_domain_intents", result.warnings)

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
        self.assertEqual(result.occurred_at, "2026-07-16T00:00:00+08:00")
        self.assertEqual(result.payload["sleep_date"], "2026-07-16")
        self.assertEqual(result.payload["occurred_at_source"], "sleep_wake_date")

    def test_relative_duration_is_applied_before_message_time(self) -> None:
        result = parse_checkin_text("1小时前吃了三文鱼", now=NOW)
        self.assertEqual(result.occurred_at, "2026-07-16T09:15:00+08:00")
        self.assertEqual(result.payload["occurred_at_source"], "relative_duration")

    def test_explicit_datetime_has_priority_over_relative_phrase(self) -> None:
        result = parse_checkin_text(
            "2026-07-15 18:30 吃了三文鱼，补充说明是1小时前想到的",
            now=NOW,
        )
        self.assertEqual(result.occurred_at, "2026-07-15T18:30:00+08:00")
        self.assertEqual(result.payload["occurred_at_source"], "explicit_date")

    def test_half_hour_relative_duration(self) -> None:
        result = parse_checkin_text("半小时前喝了牛奶", now=NOW)
        self.assertEqual(result.occurred_at, "2026-07-16T09:45:00+08:00")

    def test_same_day_meal_name_does_not_fabricate_clock(self) -> None:
        result = parse_checkin_text("今天早餐吃了燕麦", now=NOW)
        self.assertEqual(result.occurred_at, "2026-07-16T10:15:00+08:00")

    def test_sleep_plan_is_not_saved_as_completed_sleep(self) -> None:
        with self.assertRaises(ParseError):
            parse_checkin_text("今晚想睡8小时", now=NOW)

    def test_completed_nap_stays_on_actual_time(self) -> None:
        result = parse_checkin_text("刚午睡了30分钟", now=NOW)
        self.assertEqual(result.event_type, "sleep")
        self.assertEqual(result.occurred_at, "2026-07-16T10:15:00+08:00")

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
