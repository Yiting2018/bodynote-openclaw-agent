from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bodynote_agent.gap_check import GapCheckService
from bodynote_agent.preferences import OnboardingService
from bodynote_agent.runtime import initialize
from bodynote_agent.schedule_plan import SchedulePlanService
from bodynote_agent.service import CheckinService


class OnboardingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary_directory.name) / "runtime"
        result = initialize(self.home)
        self.database = Path(result["database"])
        self.onboarding = OnboardingService(self.database)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_defaults_are_visible_but_setup_is_incomplete(self) -> None:
        result = self.onboarding.status()

        self.assertFalse(result["onboarding_completed"])
        self.assertEqual(result["missing_setup_fields"], ["primary_goal"])
        self.assertEqual(result["schedule"]["gap_check_time"], "20:30")
        self.assertEqual(
            result["schedule"]["required_daily_fields"],
            ["movement", "nutrition", "body", "recovery"],
        )

    def test_configure_completes_setup_and_persists_preferences(self) -> None:
        result = self.onboarding.configure(
            {
                "display_name": "小乐",
                "primary_goal": "稳定减脂，不牺牲睡眠",
                "timezone": "Asia/Shanghai",
                "profile": {"height_cm": 168},
                "schedule": {
                    "gap_check_time": "20:45",
                    "daily_report_time": "22:15",
                    "weekly_report_day": "Friday",
                    "required_daily_fields": [
                        "movement",
                        "nutrition",
                        "recovery",
                        "blood_pressure",
                    ],
                    "not_applicable_daily_fields": ["blood_glucose"],
                },
                "reports": {"formats": ["png", "pdf"]},
            }
        )

        self.assertTrue(result["onboarding_completed"])
        self.assertIsNotNone(result["onboarding_completed_at"])
        self.assertEqual(result["profile"]["details"]["height_cm"], 168)
        self.assertEqual(result["schedule"]["gap_check_time"], "20:45")
        self.assertEqual(
            result["schedule"]["not_applicable_daily_fields"], ["blood_glucose"]
        )
        self.assertEqual(result["report_formats"], ["png", "pdf"])

    def test_invalid_timezone_and_time_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "IANA"):
            self.onboarding.configure(
                {"primary_goal": "改善体能", "timezone": "Moon/Base"}
            )
        with self.assertRaisesRegex(ValueError, "HH:MM"):
            self.onboarding.configure(
                {
                    "primary_goal": "改善体能",
                    "schedule": {"gap_check_time": "25:00"},
                }
            )
        with self.assertRaisesRegex(ValueError, "不能重叠"):
            self.onboarding.configure(
                {
                    "primary_goal": "改善体能",
                    "required_daily_fields": ["movement"],
                    "not_applicable_daily_fields": ["movement"],
                }
            )

    def test_gap_check_limits_prompts_to_three(self) -> None:
        self.onboarding.configure(
            {
                "primary_goal": "稳定代谢指标",
                "required_daily_fields": [
                    "movement",
                    "nutrition",
                    "body",
                    "recovery",
                    "blood_pressure",
                    "blood_glucose",
                ],
            }
        )

        result = GapCheckService(self.database).check("2026-07-16")

        self.assertTrue(result["ok"])
        self.assertFalse(result["complete"])
        self.assertEqual(len(result["missing"]), 6)
        self.assertEqual(len(result["prompts"]), 3)
        self.assertEqual(result["not_planned"], [])
        self.assertEqual(result["not_applicable"], [])
        self.assertTrue(result["report_can_continue"])

    def test_gap_check_separates_not_planned_and_not_applicable(self) -> None:
        self.onboarding.configure(
            {
                "primary_goal": "保持活动量",
                "required_daily_fields": ["movement"],
                "not_applicable_daily_fields": ["blood_glucose"],
            }
        )

        result = GapCheckService(self.database).check("2026-07-16")

        self.assertEqual(result["not_applicable"], ["blood_glucose"])
        self.assertIn("nutrition", result["not_planned"])
        self.assertNotIn("blood_glucose", result["not_planned"])

    def test_gap_check_is_complete_after_required_records(self) -> None:
        self.onboarding.configure({"primary_goal": "保持当前健康状态"})
        checkins = CheckinService(self.database)
        events = (
            ("exercise", {"activity": "walking", "steps": 8000}),
            ("meal", {"foods": ["米饭", "鸡蛋"]}),
            ("body", {"weight_kg": 62.5}),
            ("sleep", {"duration_hours": 7.2}),
        )
        for index, (event_type, payload) in enumerate(events):
            result = checkins.record_structured(
                {
                    "event_type": event_type,
                    "occurred_at": f"2026-07-16T{8 + index:02d}:00:00+08:00",
                    "payload": payload,
                }
            )
            self.assertTrue(result["ok"], result)

        result = GapCheckService(self.database).check("2026-07-16")

        self.assertTrue(result["complete"])
        self.assertEqual(result["coverage"], 1.0)
        self.assertEqual(result["confidence_hint"], "high")
        self.assertEqual(result["prompts"], [])

    def test_schedule_plan_exposes_gap_and_report_jobs(self) -> None:
        self.onboarding.configure(
            {
                "primary_goal": "改善体能",
                "schedule": {
                    "gap_check_time": "20:45",
                    "weekly_report_day": "Friday",
                },
            }
        )

        result = SchedulePlanService(self.database, self.home).plan()
        jobs = {job["id"]: job for job in result["jobs"]}

        self.assertFalse(result["mutates_openclaw"])
        self.assertTrue(result["requires_operator_admin"])
        self.assertTrue(jobs["gap_check"]["ready"])
        self.assertEqual(jobs["gap_check"]["schedule"], "45 20 * * *")
        self.assertIn("--command-argv", jobs["gap_check"]["install_argv"])
        self.assertTrue(jobs["daily_report"]["ready"])
        self.assertEqual(jobs["daily_report"]["execution"], "agent")
        self.assertIn("attachments", jobs["daily_report"]["install_command"])
        self.assertEqual(jobs["weekly_report"]["schedule"], "30 21 * * 5")

    def test_gap_check_uses_owner_timezone_for_utc_events(self) -> None:
        self.onboarding.configure(
            {
                "primary_goal": "保持活动量",
                "required_daily_fields": ["movement"],
            }
        )
        result = CheckinService(self.database).record_structured(
            {
                "event_type": "exercise",
                "occurred_at": "2026-07-15T16:30:00+00:00",
                "payload": {"activity": "walking", "steps": 5000},
            }
        )
        self.assertTrue(result["ok"])

        gap = GapCheckService(self.database).check("2026-07-16")

        self.assertTrue(gap["complete"])
        self.assertEqual(gap["event_count"], 1)


if __name__ == "__main__":
    unittest.main()
