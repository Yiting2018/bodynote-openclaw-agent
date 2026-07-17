from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bodynote_agent.config import RuntimePaths
from bodynote_agent.database import SCHEMA_VERSION, connect, initialize_database, new_id


BACKUP_DATABASE_NAME = "bodynote.sqlite3"
BACKUP_MANIFEST_NAME = "backup-manifest.json"
SENSITIVE_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".pem", ".key", ".p12"}
SENSITIVE_NAMES = {"config.toml", ".env", ".env.local", ".env.production"}
RELEASE_ROOT_FILES = {
    ".gitignore",
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "config.example.toml",
    "pyproject.toml",
}
RELEASE_DIRECTORIES = {"docs", "skill", "src", "tests"}


class BackupService:
    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    def create(self, output: Path | None = None) -> dict[str, Any]:
        if not self.paths.database.exists():
            raise ValueError("BodyNote 数据库不存在，无法备份。")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        if output is None:
            destination = self.paths.home / "backups" / f"bodynote-backup-{timestamp}.zip"
        elif output.suffix.lower() == ".zip":
            destination = output.expanduser().resolve()
        else:
            destination = output.expanduser().resolve() / f"bodynote-backup-{timestamp}.zip"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.parent.chmod(0o700)

        with tempfile.TemporaryDirectory(prefix="bodynote-backup-") as temporary:
            snapshot = Path(temporary) / BACKUP_DATABASE_NAME
            with closing(connect(self.paths.database)) as source:
                with closing(sqlite3.connect(snapshot)) as target:
                    source.backup(target)
            snapshot.chmod(0o600)
            integrity = _sqlite_integrity(snapshot)
            if integrity != "ok":
                raise RuntimeError(f"备份快照完整性检查失败：{integrity}")
            status = _database_counts(snapshot)
            manifest = {
                "format": "bodynote-backup-v1",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "schema_version": status["schema_version"],
                "profile_id": "owner",
                "event_count": status["event_count"],
                "database_sha256": _sha256(snapshot),
                "includes_reports": False,
                "sensitive": True,
            }
            manifest_path = Path(temporary) / BACKUP_MANIFEST_NAME
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary_zip = destination.with_suffix(".zip.tmp")
            with zipfile.ZipFile(
                temporary_zip, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.write(snapshot, BACKUP_DATABASE_NAME)
                archive.write(manifest_path, BACKUP_MANIFEST_NAME)
            temporary_zip.replace(destination)
        destination.chmod(0o600)
        return {
            "ok": True,
            "backup": str(destination),
            "sha256": _sha256(destination),
            "size_bytes": destination.stat().st_size,
            "manifest": manifest,
        }

    def verify(self, backup: Path) -> dict[str, Any]:
        path = backup.expanduser().resolve()
        if not path.exists():
            return {"ok": False, "valid": False, "error": "备份文件不存在。"}
        try:
            with tempfile.TemporaryDirectory(prefix="bodynote-verify-") as temporary:
                temp = Path(temporary)
                with zipfile.ZipFile(path) as archive:
                    names = set(archive.namelist())
                    if names != {BACKUP_DATABASE_NAME, BACKUP_MANIFEST_NAME}:
                        raise ValueError("备份内容不符合 BodyNote backup-v1 格式。")
                    archive.extractall(temp)
                manifest = json.loads(
                    (temp / BACKUP_MANIFEST_NAME).read_text(encoding="utf-8")
                )
                database = temp / BACKUP_DATABASE_NAME
                if manifest.get("format") != "bodynote-backup-v1":
                    raise ValueError("未知的备份格式。")
                if _sha256(database) != manifest.get("database_sha256"):
                    raise ValueError("数据库哈希与备份清单不一致。")
                integrity = _sqlite_integrity(database)
                if integrity != "ok":
                    raise ValueError(f"SQLite 完整性检查失败：{integrity}")
                counts = _database_counts(database)
                if counts["profile_count"] != 1:
                    raise ValueError("备份不符合单 owner 数据边界。")
            return {
                "ok": True,
                "valid": True,
                "backup": str(path),
                "manifest": manifest,
                "database": counts,
            }
        except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
            return {"ok": False, "valid": False, "error": str(error), "backup": str(path)}

    def restore(self, backup: Path) -> dict[str, Any]:
        verification = self.verify(backup)
        if not verification.get("valid"):
            return verification
        safety_backup = self.create()
        with tempfile.TemporaryDirectory(prefix="bodynote-restore-") as temporary:
            temp = Path(temporary)
            with zipfile.ZipFile(backup.expanduser().resolve()) as archive:
                archive.extract(BACKUP_DATABASE_NAME, temp)
            restored = temp / BACKUP_DATABASE_NAME
            replacement = self.paths.database.with_suffix(".sqlite3.restore")
            shutil.copy2(restored, replacement)
            replacement.chmod(0o600)
            replacement.replace(self.paths.database)
        initialize_database(self.paths.database)
        with closing(connect(self.paths.database)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO audit_log (
                        id, profile_id, action, target_type, target_id,
                        data_types_json, details_json, success
                    ) VALUES (?, 'owner', 'backup_restore', 'database', 'owner',
                              '["health_events","profile","reports"]', ?, 1)
                    """,
                    (
                        new_id("audit"),
                        json.dumps(
                            {
                                "source_backup_sha256": _sha256(
                                    backup.expanduser().resolve()
                                ),
                                "safety_backup": safety_backup["backup"],
                            },
                            separators=(",", ":"),
                        ),
                    ),
                )
        return {
            "ok": True,
            "restored": True,
            "backup": str(backup.expanduser().resolve()),
            "safety_backup": safety_backup["backup"],
            "schema_version": SCHEMA_VERSION,
        }


class PrivacyAuditService:
    def __init__(self, paths: RuntimePaths, project_root: Path | None = None) -> None:
        self.paths = paths
        self.project_root = project_root.resolve() if project_root else None

    def audit(self) -> dict[str, Any]:
        findings: list[dict[str, str]] = []
        for path, expected_mode in (
            (self.paths.home, 0o700),
            (self.paths.config, 0o600),
            (self.paths.database, 0o600),
            (self.paths.reports, 0o700),
        ):
            if not path.exists():
                continue
            actual = path.stat().st_mode & 0o777
            if actual & 0o077:
                findings.append(
                    {
                        "severity": "high",
                        "code": "runtime_permissions",
                        "message": f"{path} 权限为 {oct(actual)}，建议收紧到 {oct(expected_mode)}。",
                    }
                )
        for root in (self.paths.database.parent, self.paths.reports, self.paths.logs):
            if not root.exists():
                continue
            for path in root.rglob("*"):
                actual = path.stat().st_mode & 0o777
                if actual & 0o077:
                    findings.append(
                        {
                            "severity": "high",
                            "code": "runtime_child_permissions",
                            "message": f"{path} 权限为 {oct(actual)}，运行数据不应允许组或其他用户访问。",
                        }
                    )
        if self.paths.config.exists():
            config = self.paths.config.read_text(encoding="utf-8")
            if "allow_network_serving = true" in config:
                findings.append(
                    {
                        "severity": "high",
                        "code": "network_serving_enabled",
                        "message": "本地报告网络服务已启用，请确认这是 owner 的明确选择。",
                    }
                )
            if "allow_third_party_delivery = true" in config:
                findings.append(
                    {
                        "severity": "medium",
                        "code": "third_party_delivery_enabled",
                        "message": "第三方交付已启用，请复核 OpenClaw 路由和附件范围。",
                    }
                )
        if self.project_root:
            for path in _project_files(self.project_root):
                relative = path.relative_to(self.project_root)
                if path.name in SENSITIVE_NAMES or path.suffix.lower() in SENSITIVE_SUFFIXES:
                    findings.append(
                        {
                            "severity": "high",
                            "code": "sensitive_release_file",
                            "message": f"发布目录包含敏感文件：{relative}",
                        }
                    )
                if path.suffix.lower() in {".png", ".pdf", ".html", ".jsonl"} and "tests" not in relative.parts:
                    findings.append(
                        {
                            "severity": "medium",
                            "code": "generated_artifact_in_project",
                            "message": f"发布目录包含疑似运行产物：{relative}",
                        }
                    )
        high = sum(1 for item in findings if item["severity"] == "high")
        medium = sum(1 for item in findings if item["severity"] == "medium")
        return {
            "ok": high == 0,
            "passed": high == 0,
            "summary": {"high": high, "medium": medium, "total": len(findings)},
            "findings": findings,
            "checks": [
                "runtime_permissions",
                "network_serving",
                "third_party_delivery",
                "release_sensitive_files",
                "generated_artifacts",
            ],
        }


class ReleaseService:
    def __init__(self, project_root: Path, paths: RuntimePaths) -> None:
        self.project_root = project_root.resolve()
        self.paths = paths

    def build(self, output_dir: Path, version: str) -> dict[str, Any]:
        audit = PrivacyAuditService(self.paths, self.project_root).audit()
        if not audit["passed"]:
            raise ValueError("隐私审计存在高风险项，拒绝构建发布包。")
        destination_dir = output_dir.expanduser().resolve()
        destination_dir.mkdir(parents=True, exist_ok=True)
        package = destination_dir / f"bodynote-openclaw-agent-{version}.zip"
        files = _release_files(self.project_root)
        manifest_files = []
        for path in files:
            relative = path.relative_to(self.project_root).as_posix()
            manifest_files.append(
                {"path": relative, "sha256": _sha256(path), "size_bytes": path.stat().st_size}
            )
        manifest = {
            "name": "bodynote-openclaw-agent",
            "version": version,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "files": manifest_files,
            "privacy_audit": audit["summary"],
        }
        temporary = package.with_suffix(".zip.tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(self.project_root).as_posix())
            archive.writestr(
                "RELEASE-MANIFEST.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
        temporary.replace(package)
        validation = _validate_release_archive(package)
        if not validation["valid"]:
            package.unlink(missing_ok=True)
            raise ValueError(str(validation["error"]))
        return {
            "ok": True,
            "package": str(package),
            "version": version,
            "file_count": len(files) + 1,
            "size_bytes": package.stat().st_size,
            "sha256": _sha256(package),
            "privacy_audit": audit,
        }


def _database_counts(path: Path) -> dict[str, int | None]:
    with closing(sqlite3.connect(path)) as connection:
        version = connection.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0]
        profiles = connection.execute("SELECT COUNT(*) FROM profile").fetchone()[0]
        events = connection.execute("SELECT COUNT(*) FROM health_events").fetchone()[0]
    return {
        "schema_version": version,
        "profile_count": profiles,
        "event_count": events,
    }


def _sqlite_integrity(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])


def _project_files(root: Path) -> list[Path]:
    ignored = {".git", ".venv", "__pycache__", ".pytest_cache", "dist", "build", ".bodynote", ".bodynote-delivery"}
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in ignored for part in path.relative_to(root).parts)
        and not any(
            part.endswith(".egg-info") for part in path.relative_to(root).parts
        )
        and path.suffix != ".pyc"
    ]


def _release_files(root: Path) -> list[Path]:
    result = []
    for path in _project_files(root):
        relative = path.relative_to(root)
        if len(relative.parts) == 1 and path.name in RELEASE_ROOT_FILES:
            result.append(path)
        elif relative.parts[0] in RELEASE_DIRECTORIES:
            result.append(path)
    return sorted(result)


def _validate_release_archive(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "RELEASE-MANIFEST.json" not in names:
                raise ValueError("发布包缺少 RELEASE-MANIFEST.json。")
            for name in names:
                item = Path(name)
                if item.name in SENSITIVE_NAMES or item.suffix.lower() in SENSITIVE_SUFFIXES:
                    raise ValueError(f"发布包包含敏感文件：{name}")
                if "__pycache__" in item.parts or item.suffix == ".pyc":
                    raise ValueError(f"发布包包含缓存文件：{name}")
        return {"valid": True}
    except (ValueError, zipfile.BadZipFile) as error:
        return {"valid": False, "error": str(error)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
