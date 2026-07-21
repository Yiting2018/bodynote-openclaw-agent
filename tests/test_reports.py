from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from bodynote_agent.preferences import OnboardingService
from bodynote_agent.food_library import FoodLibraryService
from bodynote_agent.html_report import event_summary, event_time_label
from bodynote_agent.reports import ReportService, _pdf_period_details
from bodynote_agent.runtime import initialize
from bodynote_agent.service import CheckinService


class ReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary_directory.name) / "runtime"
        initialized = initialize(self.home)
        self.database = Path(initialized["database"])
        self.reports_root = Path(initialized["reports"])
        OnboardingService(self.database).configure(
            {"primary_goal": "保持稳定活动和睡眠"}
        )
        checkins = CheckinService(self.database)
        for day in range(10, 17):
            for event_type, payload, hour in (
                ("exercise", {"activity": "walking", "steps": 7000 + day * 100}, 18),
                ("meal", {"foods": ["米饭", "鸡蛋"], "meal_type": "dinner"}, 19),
                ("sleep", {"duration_hours": 7.2}, 7),
                ("body", {"weight_kg": 62.5 - (day - 10) * 0.05}, 8),
            ):
                result = checkins.record_structured(
                    {
                        "event_type": event_type,
                        "occurred_at": f"2026-07-{day:02d}T{hour:02d}:00:00+08:00",
                        "payload": payload,
                    }
                )
                self.assertTrue(result["ok"], result)
        self.service = ReportService(self.database, self.reports_root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_daily_html_and_dashboard_are_idempotent(self) -> None:
        FoodLibraryService(self.database).add_food(
            {
                "title": "示例蛋白粉",
                "category": "supplement",
                "aliases": ["蛋白粉"],
                "nutrition_per_serving": {"calories_kcal": 120, "protein_g": 24},
                "source_type": "user_label",
            }
        )
        first = self.service.generate(
            "daily", "2026-07-16", formats=["html"]
        )
        second = self.service.generate(
            "daily", "2026-07-16", formats=["html"]
        )

        self.assertTrue(first["ok"])
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        html_path = Path(first["artifacts"]["html"]["path"])
        dashboard = Path(first["dashboard"])
        self.assertTrue(html_path.exists())
        self.assertTrue(dashboard.exists())
        content = html_path.read_text(encoding="utf-8")
        self.assertIn("BodyNote", content)
        self.assertIn("维度评分", content)
        self.assertIn("width:min(100%,560px)", content)
        self.assertIn("今天发生了什么", content)
        self.assertNotIn("bodynote.sqlite3", content)
        dashboard_content = dashboard.read_text(encoding="utf-8")
        self.assertIn("记录时间轴", dashboard_content)
        self.assertIn("后台原始数据", dashboard_content)
        self.assertIn("活动训练", dashboard_content)
        self.assertIn("身体状态", dashboard_content)
        self.assertNotIn("生成报告</span>", dashboard_content)
        self.assertIn("行为评分与身体变化", dashboard_content)
        self.assertIn('data-period="custom"', dashboard_content)
        self.assertIn("每日评分与身体变化", dashboard_content)
        self.assertIn("raw_text", dashboard_content)
        self.assertIn("个人食物库", dashboard_content)
        self.assertIn("示例蛋白粉", dashboard_content)
        self.assertIn("food_library", dashboard_content)

    def test_weekly_and_monthly_use_distinct_sections(self) -> None:
        weekly = self.service.generate(
            "weekly", "2026-07-16", formats=["html"]
        )
        monthly = self.service.generate(
            "monthly", "2026-07", formats=["html"]
        )

        weekly_html = Path(weekly["artifacts"]["html"]["path"]).read_text(
            encoding="utf-8"
        )
        monthly_html = Path(monthly["artifacts"]["html"]["path"]).read_text(
            encoding="utf-8"
        )
        self.assertIn("本周真实指标变化", weekly_html)
        self.assertIn("本周结构", weekly_html)
        self.assertNotIn("身体变化", weekly_html)
        self.assertIn("本月关键变化", monthly_html)
        self.assertIn("行为稳定性", monthly_html)
        self.assertNotIn("七日趋势", monthly_html)
        monthly_model = self.service.analytics.analyze("monthly", "2026-07")
        body_row = dict(_pdf_period_details(monthly_model))["身体变化"]
        self.assertIn("体重", body_row)
        self.assertNotIn("weight_kg", body_row)

    def test_delivery_manifest_contains_only_report_artifacts(self) -> None:
        delivery_dir = self.home / "agent-workspace" / ".bodynote-delivery"
        result = self.service.generate(
            "daily",
            "2026-07-16",
            formats=["html"],
            delivery_dir=delivery_dir,
        )

        self.assertEqual(len(result["attachments"]), 1)
        self.assertEqual(result["attachments"][0]["mime_type"], "text/html")
        self.assertNotIn("sqlite", result["attachments"][0]["path"])
        self.assertTrue(
            Path(result["attachments"][0]["path"]).is_relative_to(
                delivery_dir.resolve()
            )
        )
        self.assertTrue(result["delivery_staged"])
        self.assertEqual(delivery_dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual((delivery_dir / "daily").stat().st_mode & 0o777, 0o700)
        self.assertEqual(
            Path(result["attachments"][0]["path"]).stat().st_mode & 0o777,
            0o600,
        )
        listing = self.service.list_reports()
        self.assertEqual(listing["count"], 1)

    def test_png_and_pdf_render_when_dependencies_are_available(self) -> None:
        try:
            import PIL  # noqa: F401
            import reportlab  # noqa: F401
        except ImportError:
            self.skipTest("Pillow/reportlab are not installed in this interpreter")

        result = self.service.generate(
            "daily", "2026-07-16", formats=["png", "pdf"]
        )

        from PIL import Image

        png_path = Path(result["artifacts"]["png"]["path"])
        pdf_path = Path(result["artifacts"]["pdf"]["path"])
        with Image.open(png_path) as image:
            self.assertEqual(image.width, 1080)
            self.assertGreaterEqual(image.height, 1920)
        self.assertTrue(pdf_path.read_bytes().startswith(b"%PDF"))
        self.assertGreater(pdf_path.stat().st_size, 2500)

    def test_daily_png_is_one_adaptive_long_image_with_all_events(self) -> None:
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow is not installed in this interpreter")
        checkins = CheckinService(self.database)
        for minute in range(4):
            result = checkins.record_structured(
                {
                    "event_type": "mood",
                    "occurred_at": f"2026-07-16T20:{minute:02d}:00+08:00",
                    "payload": {"mood": "calm", "intensity": 5},
                }
            )
            self.assertTrue(result["ok"], result)

        legacy_page = self.reports_root / "daily" / "2026-07-16" / "report-2.png"
        legacy_page.parent.mkdir(parents=True, exist_ok=True)
        legacy_page.write_bytes(b"old continuation")

        generated = self.service.generate("daily", "2026-07-16", formats=["png"])

        self.assertIn("png", generated["artifacts"])
        self.assertNotIn("png_2", generated["artifacts"])
        self.assertEqual(len(generated["attachments"]), 1)
        self.assertFalse(legacy_page.exists())
        from PIL import Image, ImageStat

        with Image.open(generated["artifacts"]["png"]["path"]) as image:
            self.assertEqual(image.width, 1080)
            self.assertGreater(image.height, 1920)
            lower_content = image.crop((40, int(image.height * 0.72), 1040, image.height - 40))
            self.assertGreater(sum(ImageStat.Stat(lower_content).var), 1.0)

    def test_sleep_and_medical_timeline_use_human_summary(self) -> None:
        sleep = {
            "event_type": "sleep",
            "occurred_at": "2026-07-16T00:00:00+08:00",
            "payload": {
                "duration_hours": 7.2,
                "sleep_date": "2026-07-16",
                "occurred_at_source": "sleep_wake_date",
            },
        }
        medical = {
            "event_type": "medical_report",
            "occurred_at": "2026-07-16T11:00:00+08:00",
            "payload": {
                "report_type": "体检报告",
                "findings": [{"name": "尿酸"}, {"name": "胆固醇"}],
                "action_candidates": ["复查"],
            },
        }

        self.assertEqual(event_time_label(sleep), "昨夜")
        self.assertEqual(event_summary(medical), "体检报告 · 2 项需关注 · 1 项后续建议")
        self.assertNotIn("findings", event_summary(medical))

    def test_scheduled_monthly_report_only_runs_on_local_month_end(self) -> None:
        skipped = self.service.generate(
            "monthly",
            formats=["html"],
            scheduled=True,
            now=datetime.fromisoformat("2026-07-30T21:30:00+08:00"),
        )
        generated = self.service.generate(
            "monthly",
            formats=["html"],
            scheduled=True,
            now=datetime.fromisoformat("2026-07-31T21:30:00+08:00"),
        )

        self.assertTrue(skipped["skipped"])
        self.assertEqual(skipped["summary"], "NO_REPLY")
        self.assertTrue(generated["ok"])
        self.assertFalse(generated.get("skipped", False))


if __name__ == "__main__":
    unittest.main()
