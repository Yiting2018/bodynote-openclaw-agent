from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from bodynote_agent.runtime import initialize, status


class RuntimeTest(unittest.TestCase):
    def test_initialize_creates_external_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "bodynote"
            result = initialize(home)

            self.assertTrue(Path(result["config"]).exists())
            self.assertTrue(Path(result["database"]).exists())
            self.assertTrue(Path(result["reports"]).is_dir())

            state = status(home)
            self.assertEqual(state["database"]["schema_version"], 5)
            self.assertEqual(state["database"]["profile_count"], 1)
            self.assertEqual(state["database"]["event_count"], 0)

    def test_schema_has_single_owner_and_no_channel_identity_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "bodynote"
            result = initialize(home)

            with closing(sqlite3.connect(result["database"])) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                owner = connection.execute("SELECT id FROM profile").fetchone()[0]

            self.assertEqual(owner, "owner")
            self.assertNotIn("external_identities", tables)
            self.assertNotIn("user_identity_map", tables)

    def test_initialize_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "bodynote"
            first = initialize(home)
            second = initialize(home)

            self.assertTrue(first["config_created"])
            self.assertTrue(first["database_created"])
            self.assertFalse(second["config_created"])
            self.assertFalse(second["database_created"])

    def test_initialize_repairs_existing_runtime_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "bodynote"
            result = initialize(home)
            report = home / "reports" / "daily" / "2026-07-16" / "report.json"
            report.parent.mkdir(parents=True)
            report.write_text("{}", encoding="utf-8")
            report.parent.parent.chmod(0o755)
            report.chmod(0o644)
            Path(result["config"]).chmod(0o644)

            initialize(home)

            self.assertEqual(report.parent.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(report.stat().st_mode & 0o777, 0o600)
            self.assertEqual(Path(result["config"]).stat().st_mode & 0o777, 0o600)

    def test_initialize_migrates_v1_health_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "bodynote"
            database = home / "data" / "bodynote.sqlite3"
            database.parent.mkdir(parents=True)
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    """
                    CREATE TABLE health_events (
                        id TEXT PRIMARY KEY,
                        profile_id TEXT NOT NULL DEFAULT 'owner',
                        event_type TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        source TEXT NOT NULL DEFAULT 'openclaw',
                        source_context_json TEXT NOT NULL DEFAULT '{}',
                        raw_text TEXT,
                        confidence REAL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.commit()

            initialize(home)

            with closing(sqlite3.connect(database)) as connection:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(health_events)")
                }
                version = connection.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0]

            self.assertEqual(version, 5)
            self.assertTrue(
                {"idempotency_key", "revision", "updated_at", "deleted_at"}.issubset(columns)
            )

    def test_initialize_migrates_v2_profile_and_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "bodynote"
            database = home / "data" / "bodynote.sqlite3"
            database.parent.mkdir(parents=True)
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    """
                    CREATE TABLE profile (
                        id TEXT PRIMARY KEY,
                        display_name TEXT NOT NULL DEFAULT '',
                        timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                        primary_goal TEXT,
                        profile_json TEXT NOT NULL DEFAULT '{}',
                        onboarding_completed INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE schedule_preferences (
                        profile_id TEXT PRIMARY KEY,
                        gap_check_time TEXT NOT NULL DEFAULT '20:30',
                        daily_report_time TEXT NOT NULL DEFAULT '22:30',
                        weekly_report_day TEXT NOT NULL DEFAULT 'Sunday',
                        weekly_report_time TEXT NOT NULL DEFAULT '21:30',
                        monthly_report_policy TEXT NOT NULL DEFAULT 'last_day',
                        monthly_report_time TEXT NOT NULL DEFAULT '21:30',
                        output_formats_json TEXT NOT NULL DEFAULT '["html","png","pdf"]',
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.execute("INSERT INTO profile(id) VALUES ('owner')")
                connection.execute(
                    "INSERT INTO schedule_preferences(profile_id) VALUES ('owner')"
                )
                connection.commit()

            initialize(home)

            with closing(sqlite3.connect(database)) as connection:
                profile_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(profile)")
                }
                schedule_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(schedule_preferences)"
                    )
                }
                required = connection.execute(
                    """
                    SELECT required_daily_fields_json, not_applicable_daily_fields_json
                    FROM schedule_preferences
                    """
                ).fetchone()

            self.assertIn("onboarding_completed_at", profile_columns)
            self.assertIn("required_daily_fields_json", schedule_columns)
            self.assertIn("not_applicable_daily_fields_json", schedule_columns)
            self.assertEqual(
                required[0], '["movement","nutrition","body","recovery"]'
            )
            self.assertEqual(required[1], "[]")

    def test_initialize_migrates_v3_analysis_and_report_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "bodynote"
            database = home / "data" / "bodynote.sqlite3"
            database.parent.mkdir(parents=True)
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    """
                    CREATE TABLE insight_snapshots (
                        id TEXT PRIMARY KEY,
                        profile_id TEXT NOT NULL DEFAULT 'owner',
                        period_type TEXT NOT NULL,
                        period_key TEXT NOT NULL,
                        health_score INTEGER,
                        confidence REAL NOT NULL,
                        status TEXT,
                        insights_json TEXT NOT NULL DEFAULT '[]',
                        generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(profile_id, period_type, period_key)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE report_runs (
                        id TEXT PRIMARY KEY,
                        profile_id TEXT NOT NULL DEFAULT 'owner',
                        report_type TEXT NOT NULL,
                        period_key TEXT NOT NULL,
                        status TEXT NOT NULL,
                        confidence REAL,
                        artifact_manifest_json TEXT NOT NULL DEFAULT '{}',
                        error_message TEXT,
                        generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(profile_id, report_type, period_key)
                    )
                    """
                )
                connection.commit()

            initialize(home)

            with closing(sqlite3.connect(database)) as connection:
                insight_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(insight_snapshots)"
                    )
                }
                report_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(report_runs)")
                }

            self.assertTrue(
                {"modules_json", "actions_json", "summary_json"}.issubset(
                    insight_columns
                )
            )
            self.assertTrue({"input_hash", "updated_at"}.issubset(report_columns))


if __name__ == "__main__":
    unittest.main()
