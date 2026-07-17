from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4


SCHEMA_VERSION = 4

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS profile (
    id TEXT PRIMARY KEY CHECK (id = 'owner'),
    display_name TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    primary_goal TEXT,
    profile_json TEXT NOT NULL DEFAULT '{}',
    onboarding_completed INTEGER NOT NULL DEFAULT 0,
    onboarding_completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schedule_preferences (
    profile_id TEXT PRIMARY KEY REFERENCES profile(id) ON DELETE CASCADE,
    gap_check_time TEXT NOT NULL DEFAULT '20:30',
    daily_report_time TEXT NOT NULL DEFAULT '22:30',
    weekly_report_day TEXT NOT NULL DEFAULT 'Sunday',
    weekly_report_time TEXT NOT NULL DEFAULT '21:30',
    monthly_report_policy TEXT NOT NULL DEFAULT 'last_day',
    monthly_report_time TEXT NOT NULL DEFAULT '21:30',
    output_formats_json TEXT NOT NULL DEFAULT '["html","png","pdf"]',
    required_daily_fields_json TEXT NOT NULL DEFAULT '["movement","nutrition","body","recovery"]',
    not_applicable_daily_fields_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS health_events (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL DEFAULT 'owner' REFERENCES profile(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'openclaw',
    source_context_json TEXT NOT NULL DEFAULT '{}',
    raw_text TEXT,
    confidence REAL,
    idempotency_key TEXT,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_health_events_type_time
    ON health_events(profile_id, event_type, occurred_at DESC);

CREATE TABLE IF NOT EXISTS action_items (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL DEFAULT 'owner' REFERENCES profile(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    title TEXT NOT NULL,
    due_at TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    rationale TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS insight_snapshots (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL DEFAULT 'owner' REFERENCES profile(id) ON DELETE CASCADE,
    period_type TEXT NOT NULL,
    period_key TEXT NOT NULL,
    health_score INTEGER,
    confidence REAL NOT NULL,
    status TEXT,
    insights_json TEXT NOT NULL DEFAULT '[]',
    modules_json TEXT NOT NULL DEFAULT '{}',
    actions_json TEXT NOT NULL DEFAULT '[]',
    summary_json TEXT NOT NULL DEFAULT '{}',
    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(profile_id, period_type, period_key)
);

CREATE TABLE IF NOT EXISTS report_runs (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL DEFAULT 'owner' REFERENCES profile(id) ON DELETE CASCADE,
    report_type TEXT NOT NULL,
    period_key TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL,
    artifact_manifest_json TEXT NOT NULL DEFAULT '{}',
    input_hash TEXT,
    error_message TEXT,
    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(profile_id, report_type, period_key)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL DEFAULT 'owner' REFERENCES profile(id) ON DELETE CASCADE,
    request_id TEXT,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    data_types_json TEXT NOT NULL DEFAULT '[]',
    details_json TEXT NOT NULL DEFAULT '{}',
    success INTEGER NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    if column not in _column_names(connection, table):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_schema(connection: sqlite3.Connection) -> None:
    _ensure_column(connection, "profile", "onboarding_completed_at", "TEXT")
    _ensure_column(
        connection,
        "schedule_preferences",
        "required_daily_fields_json",
        "TEXT NOT NULL DEFAULT '[\"movement\",\"nutrition\",\"body\",\"recovery\"]'",
    )
    _ensure_column(
        connection,
        "schedule_preferences",
        "not_applicable_daily_fields_json",
        "TEXT NOT NULL DEFAULT '[]'",
    )

    _ensure_column(
        connection, "insight_snapshots", "modules_json", "TEXT NOT NULL DEFAULT '{}'"
    )
    _ensure_column(
        connection, "insight_snapshots", "actions_json", "TEXT NOT NULL DEFAULT '[]'"
    )
    _ensure_column(
        connection, "insight_snapshots", "summary_json", "TEXT NOT NULL DEFAULT '{}'"
    )
    _ensure_column(connection, "report_runs", "input_hash", "TEXT")
    _ensure_column(
        connection,
        "report_runs",
        "updated_at",
        "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    )

    _ensure_column(connection, "health_events", "idempotency_key", "TEXT")
    _ensure_column(connection, "health_events", "revision", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(connection, "health_events", "updated_at", "TEXT")
    _ensure_column(connection, "health_events", "deleted_at", "TEXT")
    connection.execute(
        "UPDATE health_events SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)"
    )

    _ensure_column(connection, "audit_log", "request_id", "TEXT")
    _ensure_column(connection, "audit_log", "target_type", "TEXT")
    _ensure_column(connection, "audit_log", "target_id", "TEXT")
    _ensure_column(connection, "audit_log", "details_json", "TEXT NOT NULL DEFAULT '{}'")

    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_health_events_idempotency
        ON health_events(profile_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_health_events_active_time
        ON health_events(profile_id, occurred_at DESC)
        WHERE deleted_at IS NULL
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_target
        ON audit_log(profile_id, target_type, target_id, created_at DESC)
        """
    )


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as connection:
        with connection:
            connection.executescript(SCHEMA_SQL)
            _migrate_schema(connection)
            connection.execute(
                "INSERT OR IGNORE INTO schema_meta(version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            connection.execute("INSERT OR IGNORE INTO profile(id) VALUES ('owner')")
            connection.execute(
                "INSERT OR IGNORE INTO schedule_preferences(profile_id) VALUES ('owner')"
            )
    path.chmod(0o600)


def database_status(path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "exists": False,
            "schema_version": None,
            "profile_count": 0,
            "event_count": 0,
        }

    with closing(connect(path)) as connection:
        version_row = connection.execute(
            "SELECT MAX(version) AS version FROM schema_meta"
        ).fetchone()
        profile_count = connection.execute("SELECT COUNT(*) FROM profile").fetchone()[0]
        event_count = connection.execute("SELECT COUNT(*) FROM health_events").fetchone()[0]
    return {
        "exists": True,
        "schema_version": version_row["version"],
        "profile_count": profile_count,
        "event_count": event_count,
    }


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"
