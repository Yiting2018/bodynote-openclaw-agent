from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from bodynote_agent.config import runtime_paths
from bodynote_agent.maintenance import BackupService, PrivacyAuditService, ReleaseService
from bodynote_agent.preferences import OnboardingService
from bodynote_agent.runtime import initialize
from bodynote_agent.service import CheckinService


class MaintenanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.home = self.root / "runtime"
        initialize(self.home)
        self.paths = runtime_paths(self.home)
        OnboardingService(self.paths.database).configure(
            {"primary_goal": "稳定健康记录"}
        )
        self.checkins = CheckinService(self.paths.database)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def record(self, key: str, steps: int) -> None:
        result = self.checkins.record_structured(
            {
                "event_type": "exercise",
                "occurred_at": "2026-07-16T18:00:00+08:00",
                "payload": {"activity": "walking", "steps": steps},
                "idempotency_key": key,
            }
        )
        self.assertTrue(result["ok"], result)

    def test_backup_verify_and_restore_with_safety_backup(self) -> None:
        self.record("first", 6000)
        service = BackupService(self.paths)
        created = service.create(self.root / "exports")
        verified = service.verify(Path(created["backup"]))
        self.assertTrue(verified["valid"])
        self.assertEqual(verified["manifest"]["event_count"], 1)

        self.record("second", 8000)
        restored = service.restore(Path(created["backup"]))

        self.assertTrue(restored["restored"])
        self.assertTrue(Path(restored["safety_backup"]).exists())
        events = CheckinService(self.paths.database).list_events()
        self.assertEqual(events["count"], 1)

    def test_corrupt_backup_is_rejected(self) -> None:
        corrupt = self.root / "corrupt.zip"
        corrupt.write_bytes(b"not a zip")

        result = BackupService(self.paths).verify(corrupt)

        self.assertFalse(result["valid"])

    def test_privacy_audit_passes_for_private_runtime(self) -> None:
        project = self.root / "project"
        project.mkdir()
        (project / "README.md").write_text("clean", encoding="utf-8")

        result = PrivacyAuditService(self.paths, project).audit()

        self.assertTrue(result["passed"], result)
        self.assertEqual(result["summary"]["high"], 0)

    def test_privacy_audit_blocks_database_in_release_source(self) -> None:
        project = self.root / "project"
        project.mkdir()
        (project / "private.sqlite3").write_bytes(b"secret")

        result = PrivacyAuditService(self.paths, project).audit()

        self.assertFalse(result["passed"])
        self.assertEqual(result["findings"][0]["code"], "sensitive_release_file")

    def test_release_archive_uses_allowlist_and_manifest(self) -> None:
        project = self.root / "project"
        (project / "src" / "package").mkdir(parents=True)
        (project / "docs").mkdir()
        (project / "README.md").write_text("BodyNote", encoding="utf-8")
        (project / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
        (project / "src" / "package" / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
        egg_info = project / "src" / "package.egg-info"
        egg_info.mkdir()
        (egg_info / "PKG-INFO").write_text("generated", encoding="utf-8")
        (project / "docs" / "guide.md").write_text("guide", encoding="utf-8")
        (project / "ignored.txt").write_text("ignored", encoding="utf-8")

        result = ReleaseService(project, self.paths).build(
            self.root / "dist", "0.1.0"
        )

        with zipfile.ZipFile(result["package"]) as archive:
            names = set(archive.namelist())
        self.assertIn("README.md", names)
        self.assertIn("src/package/core.py", names)
        self.assertIn("RELEASE-MANIFEST.json", names)
        self.assertNotIn("ignored.txt", names)
        self.assertNotIn("src/package.egg-info/PKG-INFO", names)


if __name__ == "__main__":
    unittest.main()
