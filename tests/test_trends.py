from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bodynote_agent.cycle import CycleForecastService
from bodynote_agent.gap_check import GapCheckService
from bodynote_agent.preferences import OnboardingService
from bodynote_agent.reference_library import ReferenceLibraryService
from bodynote_agent.runtime import initialize
from bodynote_agent.service import CheckinService
from bodynote_agent.trends import TrendAnalysisService


class TrendAnalysisTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary_directory.name) / "runtime"
        initialized = initialize(self.home)
        self.database = Path(initialized["database"])
        self.onboarding = OnboardingService(self.database)
        self.onboarding.configure(
            {
                "display_name": "测试用户",
                "primary_goal": "增肌并保持恢复",
                "profile": {
                    "birth_date": "1993-06-10",
                    "height_cm": 168,
                    "cycle_tracking_enabled": True,
                    "cycle_reminder_days_before": 3,
                },
            }
        )
        self.checkins = CheckinService(self.database)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def record(self, event_type: str, occurred_at: str, payload: dict) -> None:
        result = self.checkins.record_structured(
            {"event_type": event_type, "occurred_at": occurred_at, "payload": payload}
        )
        self.assertTrue(result["ok"], result)

    def test_natural_week_metrics_and_relationship_clues(self) -> None:
        for index, day in enumerate(range(6, 17)):
            date = f"2026-07-{day:02d}"
            self.record(
                "exercise", f"{date}T18:00:00+08:00",
                {
                    "activity": "抗阻训练" if day % 2 == 0 else "walking",
                    "steps": 6000 + index * 300,
                    "duration_min": 35,
                    "calories_kcal": 220,
                    "volume_kg": 3000 + index * 100,
                },
            )
            self.record(
                "meal", f"{date}T12:00:00+08:00",
                {
                    "meal_type": "lunch", "foods": ["米饭", "鸡胸"],
                    "calories_kcal": 650, "protein_g": 80 + index,
                },
            )
            self.record(
                "body", f"{date}T07:30:00+08:00",
                {"weight_kg": 62 + index * 0.05, "skeletal_muscle_kg": 24 + index * 0.04},
            )

        result = TrendAnalysisService(self.database).analyze(
            "2026-07-16",
            timezone_name="Asia/Shanghai",
            profile=self.onboarding.status()["profile"],
        )

        weekly = result["periods"]["weekly"]
        self.assertEqual(weekly["range"], {"start": "2026-07-13", "end": "2026-07-16"})
        self.assertEqual(
            weekly["comparison_range"], {"start": "2026-07-09", "end": "2026-07-12"}
        )
        self.assertGreater(weekly["metrics"]["steps"]["current"], 0)
        self.assertGreater(weekly["metrics"]["protein_g"]["current"], 0)
        self.assertTrue(weekly["relationships"])
        self.assertEqual(len(weekly["dimension_scores"]), 4)
        self.assertIsNotNone(weekly["dimension_scores"][0]["current"])
        self.assertGreaterEqual(len(result["daily_series"]), 365)
        self.assertEqual(result["daily_series"][-1]["date"], "2026-07-16")
        self.assertIn("不代表因果", result["analysis_policy"]["language"])

    def test_cycle_forecast_and_gap_check_reminder(self) -> None:
        self.record(
            "menstrual_cycle", "2026-05-22T08:00:00+08:00",
            {"phase": "menstrual", "cycle_day": 1, "period_started": True},
        )
        self.record(
            "menstrual_cycle", "2026-06-19T08:00:00+08:00",
            {"phase": "menstrual", "cycle_day": 1, "period_started": True},
        )
        forecast = CycleForecastService(self.database).forecast(
            "2026-07-14",
            timezone_name="Asia/Shanghai",
            profile_details=self.onboarding.status()["profile"]["details"],
        )
        self.assertEqual(forecast["predicted_next_start"], "2026-07-17")
        self.assertTrue(forecast["reminder_due"])
        self.assertEqual(forecast["phase_label"], "黄体期")
        trends = TrendAnalysisService(self.database).analyze(
            "2026-07-14",
            timezone_name="Asia/Shanghai",
            profile=self.onboarding.status()["profile"],
        )
        self.assertTrue(trends["cycle"]["support"]["visible"])
        self.assertIn("碳水", trends["cycle"]["support"]["action"])
        gap = GapCheckService(self.database).check("2026-07-14")
        self.assertTrue(gap["cycle_forecast"]["reminder_due"])
        self.assertIn("经期", gap["prompt"])

    def test_reference_library_keeps_structured_notes(self) -> None:
        library = ReferenceLibraryService(self.database)
        added = library.add(
            {
                "title": "我的抗阻训练参考",
                "source_type": "user_note",
                "scope": ["strength"],
                "rules": [{"topic": "progression", "note": "按个人恢复调整"}],
                "citations": [{"page": 42, "label": "训练原则"}],
            }
        )
        guide = added["guide"]
        self.assertTrue(guide["enabled"])
        self.assertEqual(library.list(enabled_only=True)["count"], 1)
        library.set_enabled(guide["id"], False)
        self.assertEqual(library.list(enabled_only=True)["count"], 0)

    def test_profile_detail_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "height_cm"):
            self.onboarding.configure({"profile": {"height_cm": 20}})
        with self.assertRaisesRegex(ValueError, "birth_date"):
            self.onboarding.configure({"profile": {"birth_date": "not-a-date"}})
        with self.assertRaisesRegex(ValueError, "daily_protein_target_g"):
            self.onboarding.configure({"profile": {"daily_protein_target_g": 2}})


if __name__ == "__main__":
    unittest.main()
