from __future__ import annotations

from pathlib import Path

from bodynote_agent.config import (
    ensure_default_config,
    ensure_runtime_directories,
    ensure_runtime_permissions,
    runtime_paths,
)
from bodynote_agent.database import database_status, initialize_database


def initialize(home: str | Path | None = None) -> dict[str, object]:
    paths = runtime_paths(home)
    ensure_runtime_directories(paths)
    config_created = ensure_default_config(paths)
    database_created = not paths.database.exists()
    initialize_database(paths.database)
    ensure_runtime_permissions(paths)
    return {
        "home": str(paths.home),
        "config": str(paths.config),
        "database": str(paths.database),
        "reports": str(paths.reports),
        "config_created": config_created,
        "database_created": database_created,
    }


def status(home: str | Path | None = None) -> dict[str, object]:
    paths = runtime_paths(home)
    return {
        "home": str(paths.home),
        "config_exists": paths.config.exists(),
        "reports_exists": paths.reports.exists(),
        "database": database_status(paths.database),
        "capabilities": [
            "init",
            "status",
            "checkin.text",
            "checkin.structured",
            "events.list",
            "events.get",
            "events.update",
            "events.delete",
            "onboarding.status",
            "onboarding.configure",
            "gap-check",
            "schedule.plan",
            "analysis.daily",
            "analysis.weekly",
            "analysis.monthly",
            "report.daily",
            "report.weekly",
            "report.monthly",
            "dashboard.build",
            "reference.add",
            "reference.list",
            "reference.enable",
            "reference.disable",
            "backup.create",
            "backup.verify",
            "backup.restore",
            "privacy.audit",
            "release.build",
        ],
        "development_phase": "m7-release-ready",
    }
