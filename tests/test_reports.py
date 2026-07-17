from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from bodynote_agent.preferences import OnboardingService
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
        self.assertIn("四个健康维度", content)
        self.assertIn("@media (max-width: 760px)", content)
        self.assertNotIn("bodynote.sqlite3", content)

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
        self.assertIn("七日趋势", weekly_html)
        self.assertIn("本周结构", weekly_html)
        self.assertNotIn("身体变化", weekly_html)
        self.assertIn("身体变化", monthly_html)
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
            self.assertEqual(image.size, (1080, 1920))
        self.assertTrue(pdf_path.read_bytes().startswith(b"%PDF"))
        self.assertGreater(pdf_path.stat().st_size, 2500)

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
