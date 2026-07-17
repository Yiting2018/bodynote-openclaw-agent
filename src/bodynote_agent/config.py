from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG = """[app]
profile_id = "owner"
language = "zh-CN"

[privacy]
allow_network_serving = false
allow_third_party_delivery = false
"""


@dataclass(frozen=True)
class RuntimePaths:
    home: Path
    config: Path
    database: Path
    reports: Path
    logs: Path


def resolve_home(value: str | Path | None = None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    configured = os.getenv("BODYNOTE_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".bodynote").resolve()


def runtime_paths(home: str | Path | None = None) -> RuntimePaths:
    root = resolve_home(home)
    return RuntimePaths(
        home=root,
        config=root / "config.toml",
        database=root / "data" / "bodynote.sqlite3",
        reports=root / "reports",
        logs=root / "logs",
    )


def ensure_runtime_directories(paths: RuntimePaths) -> None:
    paths.home.mkdir(parents=True, exist_ok=True)
    paths.database.parent.mkdir(parents=True, exist_ok=True)
    paths.reports.mkdir(parents=True, exist_ok=True)
    paths.logs.mkdir(parents=True, exist_ok=True)
    for directory in (
        paths.home,
        paths.database.parent,
        paths.reports,
        paths.logs,
    ):
        directory.chmod(0o700)


def ensure_runtime_permissions(paths: RuntimePaths) -> None:
    """Keep existing runtime data private after upgrades as well as fresh installs."""
    roots = (
        paths.home,
        paths.database.parent,
        paths.reports,
        paths.logs,
        paths.home / "backups",
    )
    for root in roots:
        if not root.exists() or root.is_symlink():
            continue
        root.chmod(0o700)
        for path in root.rglob("*"):
            if path.is_symlink():
                continue
            path.chmod(0o700 if path.is_dir() else 0o600)


def ensure_default_config(paths: RuntimePaths) -> bool:
    if paths.config.exists():
        return False
    paths.config.write_text(DEFAULT_CONFIG, encoding="utf-8")
    paths.config.chmod(0o600)
    return True
