# Maintenance and Privacy

Read this reference for migration, backup, restore, privacy audit, and release workflows.

## Migration

Run `bodynote-agent maintenance migrate --json` after upgrading. Migrations are additive and idempotent.

## Backup

Create and verify a local owner backup:

```bash
bodynote-agent backup create --output /private/backup/directory --json
bodynote-agent backup verify /private/backup/bodynote-backup.zip --json
```

Backups contain the SQLite owner data and a hash manifest, not generated reports. They are sensitive and use private file permissions.

Restore only after explicit owner confirmation:

```bash
bodynote-agent backup restore /private/backup/bodynote-backup.zip --confirm --json
```

Restore verifies the archive, creates a safety backup of current data, replaces the database, reapplies migrations, and writes an audit record.

## Privacy and Release

Run `bodynote-agent privacy audit --project-root /path/to/project --json`. Stop release packaging when any high-severity finding remains.

Build the allowlisted public archive with `bodynote-agent release build --project-root /path/to/project --output /path/to/dist --json`. The release archive must not contain runtime config, databases, reports, backups, secrets, caches, or staged delivery files.
