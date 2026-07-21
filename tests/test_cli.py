from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from bodynote_agent.cli import main
from bodynote_agent.preferences import OnboardingService


class CliTest(unittest.TestCase):
    def test_init_and_json_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "runtime"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--home", str(home), "init"]), 0)

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(["--home", str(home), "status", "--json"]),
                    0,
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["development_phase"], "m8-food-library-ready")
            self.assertIn("checkin.text", payload["capabilities"])
            self.assertIn("events.delete", payload["capabilities"])
            self.assertIn("gap-check", payload["capabilities"])
            self.assertIn("food.add", payload["capabilities"])

    def test_text_checkin_and_event_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "runtime"
            with redirect_stdout(io.StringIO()):
                main(["--home", str(home), "init"])

            checkin_output = io.StringIO()
            with redirect_stdout(checkin_output):
                code = main(
                    [
                        "--home",
                        str(home),
                        "checkin",
                        "--text",
                        "今天走了8000步",
                        "--idempotency-key",
                        "message-1",
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            checkin = json.loads(checkin_output.getvalue())
            self.assertEqual(checkin["event"]["payload"]["steps"], 8000)

            events_output = io.StringIO()
            with redirect_stdout(events_output):
                code = main(["--home", str(home), "events", "--json"])
            self.assertEqual(code, 0)
            events = json.loads(events_output.getvalue())
            self.assertEqual(events["count"], 1)

    def test_text_checkin_accepts_explicit_occurrence_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "runtime"
            with redirect_stdout(io.StringIO()):
                main(["--home", str(home), "init"])

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(home),
                        "checkin",
                        "--text",
                        "吃了三文鱼",
                        "--at",
                        "2026-07-16T18:25:00+08:00",
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            event = json.loads(output.getvalue())["event"]
            self.assertEqual(event["occurred_at"], "2026-07-16T18:25:00+08:00")
            self.assertEqual(event["payload"]["occurred_at_source"], "explicit_override")

    def test_food_and_template_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            home = root / "runtime"
            food_file = root / "food.json"
            food_file.write_text(
                json.dumps(
                    {
                        "title": "示例水饺",
                        "aliases": ["水饺"],
                        "nutrition_per_serving": {"calories_kcal": 300, "protein_g": 25},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                main(["--home", str(home), "init"])

            added = io.StringIO()
            with redirect_stdout(added):
                self.assertEqual(
                    main(["--home", str(home), "food", "add", "--input", str(food_file), "--json"]),
                    0,
                )
            food = json.loads(added.getvalue())["food"]

            resolved = io.StringIO()
            with redirect_stdout(resolved):
                self.assertEqual(
                    main(["--home", str(home), "food", "resolve", "--text", "晚饭吃了水饺", "--json"]),
                    0,
                )
            self.assertEqual(json.loads(resolved.getvalue())["foods"][0]["food"]["id"], food["id"])

    def test_normal_command_auto_migrates_existing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "runtime"
            with redirect_stdout(io.StringIO()):
                main(["--home", str(home), "init"])

            database = home / "data" / "bodynote.sqlite3"
            OnboardingService(database).configure({"primary_goal": "保持健康"})
            with sqlite3.connect(database) as connection:
                connection.execute("DROP TABLE meal_template_items")
                connection.execute("DROP TABLE meal_templates")
                connection.execute("DROP TABLE food_aliases")
                connection.execute("DROP TABLE food_items")
                connection.commit()

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--home", str(home), "food", "list", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["count"], 0)
            with sqlite3.connect(database) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertTrue(
                {"food_items", "food_aliases", "meal_templates", "meal_template_items"}
                .issubset(tables)
            )

    def test_dashboard_command_auto_migrates_existing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "runtime"
            with redirect_stdout(io.StringIO()):
                main(["--home", str(home), "init"])
            database = home / "data" / "bodynote.sqlite3"
            OnboardingService(database).configure({"primary_goal": "保持健康"})
            with sqlite3.connect(database) as connection:
                for table in ("meal_template_items", "meal_templates", "food_aliases", "food_items"):
                    connection.execute(f"DROP TABLE {table}")
                connection.commit()
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--home", str(home), "dashboard", "build", "--date", "2026-07-16", "--json"])
            self.assertEqual(code, 0)
            dashboard = Path(json.loads(output.getvalue())["dashboard"])
            self.assertTrue(dashboard.exists())
            with sqlite3.connect(database) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"food_items", "food_aliases", "meal_templates", "meal_template_items"}.issubset(tables))

    def test_structured_checkin_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            home = root / "runtime"
            event_file = root / "event.json"
            event_file.write_text(
                json.dumps(
                    {
                        "event_type": "body",
                        "occurred_at": "2026-07-16T08:00:00+08:00",
                        "payload": {"weight_kg": 61.2},
                        "idempotency_key": "structured-1",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                main(["--home", str(home), "init"])

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(home),
                        "checkin",
                        "--input",
                        str(event_file),
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["event"]["payload"]["weight_kg"], 61.2)

    def test_event_update_and_soft_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            home = root / "runtime"
            patch_file = root / "patch.json"
            patch_file.write_text(
                json.dumps({"payload": {"steps": 9200}}, ensure_ascii=False),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                main(["--home", str(home), "init"])

            created_output = io.StringIO()
            with redirect_stdout(created_output):
                main(
                    [
                        "--home",
                        str(home),
                        "checkin",
                        "--text",
                        "今天走了8000步",
                        "--json",
                    ]
                )
            event_id = json.loads(created_output.getvalue())["event"]["id"]

            updated_output = io.StringIO()
            with redirect_stdout(updated_output):
                code = main(
                    [
                        "--home",
                        str(home),
                        "event",
                        "update",
                        event_id,
                        "--input",
                        str(patch_file),
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            updated = json.loads(updated_output.getvalue())
            self.assertEqual(updated["event"]["payload"]["steps"], 9200)
            self.assertEqual(updated["event"]["revision"], 2)

            deleted_output = io.StringIO()
            with redirect_stdout(deleted_output):
                code = main(
                    [
                        "--home",
                        str(home),
                        "event",
                        "delete",
                        event_id,
                        "--confirm",
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(deleted_output.getvalue())["deleted"])

    def test_onboarding_gap_check_and_schedule_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            home = root / "runtime"
            setup_file = root / "setup.json"
            setup_file.write_text(
                json.dumps(
                    {
                        "primary_goal": "规律运动",
                        "schedule": {"gap_check_time": "20:40"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                main(["--home", str(home), "init"])

            onboarding_output = io.StringIO()
            with redirect_stdout(onboarding_output):
                code = main(
                    [
                        "--home",
                        str(home),
                        "onboarding",
                        "configure",
                        "--input",
                        str(setup_file),
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertTrue(
                json.loads(onboarding_output.getvalue())["onboarding_completed"]
            )

            gap_output = io.StringIO()
            with redirect_stdout(gap_output):
                code = main(
                    [
                        "--home",
                        str(home),
                        "gap-check",
                        "--date",
                        "2026-07-16",
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(len(json.loads(gap_output.getvalue())["prompts"]), 3)

            plan_output = io.StringIO()
            with redirect_stdout(plan_output):
                code = main(
                    ["--home", str(home), "schedule", "plan", "--json"]
                )
            self.assertEqual(code, 0)
            jobs = json.loads(plan_output.getvalue())["jobs"]
            self.assertEqual(jobs[0]["schedule"], "40 20 * * *")
            self.assertTrue(jobs[0]["ready"])



if __name__ == "__main__":
    unittest.main()
