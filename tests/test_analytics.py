from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from bodynote_agent.analytics import HealthAnalysisService
from bodynote_agent.preferences import OnboardingService
from bodynote_agent.runtime import initialize
from bodynote_agent.service import CheckinService


class AnalyticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary_directory.name) / "runtime"
        result = initialize(self.home)
        self.database = Path(result["database"])
        OnboardingService(self.database).configure(
            {"primary_goal": "稳定体能和恢复", "timezone": "Asia/Shanghai"}
        )
        self.checkins = CheckinService(self.database)
        self.analytics = HealthAnalysisService(self.database)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def record(
        self, event_type: str, occurred_at: str, payload: dict[str, object]
    ) -> None:
        result = self.checkins.record_structured(
            {
                "event_type": event_type,
                "occurred_at": occurred_at,
                "payload": payload,
            }
        )
        self.assertTrue(result["ok"], result)

    def test_missing_data_lowers_confidence_without_red_score(self) -> None:
        result = self.analytics.analyze("daily", "2026-07-16")

        self.assertIsNone(result["health_score"])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(len(result["data_completeness"]["missing"]), 4)
        self.assertLessEqual(len(result["insights"]), 3)

    def test_daily_score_confidence_insights_and_actions(self) -> None:
        self.record(
            "exercise",
            "2026-07-16T18:00:00+08:00",
            {"activity": "walking", "steps": 9000, "duration_min": 45},
        )
        self.record(
            "meal",
            "2026-07-16T12:00:00+08:00",
            {"foods": ["米饭", "鸡肉"], "meal_type": "lunch"},
        )
        self.record(
            "body",
            "2026-07-16T08:00:00+08:00",
            {"weight_kg": 62.1},
        )
        self.record(
            "sleep",
            "2026-07-16T07:30:00+08:00",
            {"duration_hours": 7.5},
        )

        result = self.analytics.analyze("daily", "2026-07-16")

        self.assertGreaterEqual(result["health_score"], 80)
        self.assertEqual(result["status"], "green")
        self.assertEqual(result["data_completeness"]["coverage"], 1.0)
        self.assertGreaterEqual(result["confidence"], 0.9)
        self.assertLessEqual(len(result["insights"]), 3)
        self.assertLessEqual(len(result["actions"]), 3)
        self.assertEqual(result["modules"]["movement"]["label"], "活动")

        with closing(sqlite3.connect(self.database)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM insight_snapshots WHERE period_type = 'daily'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_urgent_signal_overrides_score(self) -> None:
        self.record(
            "mood",
            "2026-07-16T20:00:00+08:00",
            {"mood": "self_harm_risk", "red_flags": ["self_harm_risk"]},
        )

        result = self.analytics.analyze("daily", "2026-07-16")

        self.assertEqual(result["status"], "red")
        self.assertLessEqual(result["health_score"], 59)
        self.assertEqual(result["safety"]["level"], "urgent")
        self.assertEqual(result["insights"][0]["type"], "risk")

    def test_activity_and_nutrition_scores_expose_detailed_basis(self) -> None:
        OnboardingService(self.database).configure(
            {
                "profile": {
                    "daily_calorie_target_kcal": 2000,
                    "daily_protein_target_g": 120,
                }
            }
        )
        self.record(
            "exercise",
            "2026-07-16T18:00:00+08:00",
            {
                "activity": "抗阻训练",
                "duration_min": 55,
                "sets": 5,
                "reps": 8,
                "weight_kg": 50,
                "rpe": 8,
            },
        )
        for hour, payload in (
            (8, {"meal_type": "breakfast", "foods": ["燕麦", "酸奶", "水果"], "calories_kcal": 520, "protein_g": 35}),
            (12, {"meal_type": "lunch", "foods": ["米饭", "鸡胸", "青菜"], "calories_kcal": 720, "protein_g": 45}),
            (19, {"meal_type": "dinner", "foods": ["土豆", "牛肉", "菌菇"], "calories_kcal": 700, "protein_g": 42}),
        ):
            self.record("meal", f"2026-07-16T{hour:02d}:00:00+08:00", payload)

        result = self.analytics.analyze("daily", "2026-07-16")

        movement_labels = {item["label"] for item in result["modules"]["movement"]["basis"]}
        nutrition_labels = {item["label"] for item in result["modules"]["nutrition"]["basis"]}
        self.assertTrue({"抗阻训练", "训练强度", "活动时长"}.issubset(movement_labels))
        self.assertTrue({"食物多样性", "能量目标", "蛋白质目标"}.issubset(nutrition_labels))
        self.assertEqual(result["modules"]["movement"]["metrics"]["strength_volume_kg"], 2000)

    def test_nutrition_completeness_does_not_become_health_score(self) -> None:
        for hour, payload in (
            (8, {"meal_type": "breakfast", "foods": ["燕麦", "牛奶"], "calories_kcal": 600, "protein_g": 30}),
            (12, {"meal_type": "lunch", "foods": ["米饭", "鸡肉"], "calories_kcal": 800, "protein_g": 50}),
            (19, {"meal_type": "dinner", "foods": ["面", "鱼"], "calories_kcal": 900, "protein_g": 60}),
        ):
            self.record("meal", f"2026-07-16T{hour:02d}:00:00+08:00", payload)

        result = self.analytics.analyze("daily", "2026-07-16")

        nutrition = result["modules"]["nutrition"]
        self.assertIsNone(nutrition["score"])
        self.assertGreaterEqual(nutrition["metrics"]["data_quality_score"], 80)
        self.assertIn("暂不评价", nutrition["summary"])

    def test_body_measurement_without_personal_baseline_has_unknown_state(self) -> None:
        self.record("body", "2026-07-16T08:00:00+08:00", {"weight_kg": 62.1})
        result = self.analytics.analyze("daily", "2026-07-16")
        body = result["modules"]["body"]
        self.assertIsNone(body["score"])
        self.assertEqual(body["status"], "unknown")
        self.assertGreater(body["confidence"], 0)
        self.assertIn("基线积累中", body["summary"])

    def test_body_state_uses_personal_baseline_after_enough_measurements(self) -> None:
        for day, weight in ((13, 62.0), (14, 62.1), (15, 62.0), (16, 65.0)):
            self.record("body", f"2026-07-{day:02d}T08:00:00+08:00", {"weight_kg": weight})
        result = self.analytics.analyze("daily", "2026-07-16")
        body = result["modules"]["body"]
        self.assertIsNotNone(body["score"])
        self.assertLessEqual(body["score"], 72)
        self.assertIn("个人基线", body["summary"])

    def test_action_pipeline_exposes_evidence_safety_and_priority(self) -> None:
        OnboardingService(self.database).configure({"profile": {"daily_calorie_target_kcal": 2000}})
        self.record("meal", "2026-07-16T19:00:00+08:00", {"meal_type": "dinner", "foods": ["披萨"], "calories_kcal": 2800})
        result = self.analytics.analyze("daily", "2026-07-16")
        actions = result["actions"]
        self.assertTrue(actions)
        self.assertTrue(all(action["evidence"] for action in actions))
        self.assertTrue(all("safety" in action and "priority" in action for action in actions))
        self.assertEqual([a["priority"] for a in actions], sorted((a["priority"] for a in actions), reverse=True))

    def test_same_input_produces_same_score_headline_and_actions(self) -> None:
        self.record("exercise", "2026-07-16T18:00:00+08:00", {"activity": "walking", "steps": 9000})
        first = self.analytics.analyze("daily", "2026-07-16")
        second = self.analytics.analyze("daily", "2026-07-16")
        self.assertEqual(first["health_score"], second["health_score"])
        self.assertEqual(first["summary"], second["summary"])
        self.assertEqual(first["actions"], second["actions"])

    def test_activity_headline_uses_actual_data_instead_of_vague_stability_copy(self) -> None:
        self.record("exercise", "2026-07-16T18:00:00+08:00", {"activity": "walking", "steps": 9200, "duration_min": 48})
        self.record("sleep", "2026-07-16T07:00:00+08:00", {"duration_hours": 6.4})
        result = self.analytics.analyze("daily", "2026-07-16")
        headline = result["summary"]["headline"]
        self.assertIn("48 分钟", headline)
        self.assertIn("9200 步", headline)
        self.assertIn("睡眠还可以再补一点", headline)
        self.assertNotIn("优先保持稳定", headline)

    def test_large_nutrition_target_deviation_is_not_green(self) -> None:
        OnboardingService(self.database).configure(
            {
                "profile": {
                    "daily_calorie_target_kcal": 2200,
                    "daily_protein_target_g": 130,
                }
            }
        )
        foods = (["燕麦", "牛奶"], ["米饭", "鸡肉"], ["酸奶", "坚果"], ["意面", "三文鱼"])
        values = ((900, 70), (1400, 110), (590, 42), (1800, 120))
        for hour, meal_type, meal_foods, (calories, protein) in zip(
            (8, 12, 15, 19),
            ("breakfast", "lunch", "snack", "dinner"),
            foods,
            values,
        ):
            self.record(
                "meal",
                f"2026-07-16T{hour:02d}:00:00+08:00",
                {
                    "meal_type": meal_type,
                    "foods": list(meal_foods),
                    "calories_kcal": calories,
                    "protein_g": protein,
                },
            )

        result = self.analytics.analyze("daily", "2026-07-16")

        self.assertNotEqual(result["status"], "green")
        self.assertLessEqual(result["health_score"], 79)
        self.assertIn("能量摄入偏高", result["summary"]["headline"])
        self.assertTrue(any(action["type"] == "nutrition" for action in result["actions"]))

    def test_weekly_model_has_structure_and_trend(self) -> None:
        for day in range(10, 17):
            self.record(
                "exercise",
                f"2026-07-{day:02d}T18:00:00+08:00",
                {
                    "activity": "抗阻训练" if day == 16 else "walking",
                    "steps": 6000 + day * 100,
                },
            )
            self.record(
                "sleep",
                f"2026-07-{day:02d}T07:00:00+08:00",
                {"duration_hours": 7.0},
            )

        result = self.analytics.analyze("weekly", "2026-07-16")

        self.assertEqual(result["model"], "weekly-v1")
        self.assertEqual(len(result["trend"]), 7)
        self.assertEqual(result["movement_structure"]["sessions"], 7)
        self.assertEqual(result["movement_structure"]["strength"], 1)
        self.assertEqual(result["movement_structure"]["cardio"], 6)
        self.assertEqual(result["data_completeness"]["days_with_data"], 7)

    def test_monthly_sparse_data_downgrades_to_summary(self) -> None:
        self.record(
            "body", "2026-07-02T08:00:00+08:00", {"weight_kg": 62.5}
        )
        self.record(
            "body", "2026-07-20T08:00:00+08:00", {"weight_kg": 62.0}
        )

        result = self.analytics.analyze("monthly", "2026-07")

        self.assertEqual(result["model"], "monthly-v1")
        self.assertEqual(result["evidence_level"], "summary_only")
        self.assertTrue(result["body_change"]["sufficient"])
        self.assertEqual(result["insights"][0]["type"], "gap")


if __name__ == "__main__":
    unittest.main()
