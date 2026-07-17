# BodyNote OpenClaw Agent

BodyNote is a local-first, single-owner health workflow for OpenClaw. OpenClaw owns channels, sender authorization, sessions, and cross-channel identity links. BodyNote owns local health records, deterministic insights, scheduled gap checks, the health cockpit, and report artifacts.

This directory is the clean development and release source. It intentionally excludes user records, channel credentials, generated reports, virtual environments, and historical demos.

## Release Scope

Version 0.1.0 provides:

- A Python CLI with deterministic core workflows and Pillow/reportlab renderers.
- External runtime storage under `~/.bodynote` by default.
- A versioned SQLite schema for one owner profile.
- Deterministic text and structured-JSON health check-ins.
- Event listing, correction, soft deletion, idempotency, and audit records.
- First-use owner setup with goal, timezone, tracking preferences, and report times.
- A non-judgmental daily gap check that asks for at most three useful records.
- A reviewable OpenClaw cron plan for gap checks and daily, weekly, and monthly reports.
- Separate daily, weekly, and monthly deterministic health models.
- Health score and evidence confidence as separate values.
- Responsive local cockpit plus 1080x1920 PNG, HTML, JSON, and PDF reports.
- Workspace-staged attachment manifests for Feishu and QQ delivery through OpenClaw.
- Schema migration, verified backup/restore, privacy audit, and allowlisted release packaging.
- A separately installable OpenClaw skill under `skill/bodynote`.
- An asset inventory and phased development plan.

BodyNote does not require a separate model API. OpenClaw owns AI interaction and channel delivery; the local runtime owns deterministic health data and artifacts.

## Development Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
bodynote-agent --home /tmp/bodynote-dev init
bodynote-agent --home /tmp/bodynote-dev checkin --text "今天走了8000步" --idempotency-key message-1 --json
bodynote-agent --home /tmp/bodynote-dev events --json
bodynote-agent --home /tmp/bodynote-dev onboarding status --json
bodynote-agent --home /tmp/bodynote-dev onboarding configure --input setup.json --json
bodynote-agent --home /tmp/bodynote-dev gap-check --date 2026-07-16 --json
bodynote-agent --home /tmp/bodynote-dev analyze --type daily --period 2026-07-16 --json
bodynote-agent --home /tmp/bodynote-dev report generate --type daily --period 2026-07-16 --json
bodynote-agent --home /tmp/bodynote-dev dashboard build --date 2026-07-16 --json
bodynote-agent --home /tmp/bodynote-dev schedule plan --json
bodynote-agent --home /tmp/bodynote-dev backup create --json
bodynote-agent --home /tmp/bodynote-dev privacy audit --project-root . --json
bodynote-agent --home /tmp/bodynote-dev status --json
python3 -m unittest discover -s tests
```

`setup.json` can contain:

```json
{
  "display_name": "小乐",
  "primary_goal": "稳定减脂，不牺牲睡眠",
  "timezone": "Asia/Shanghai",
  "schedule": {
    "gap_check_time": "20:30",
    "daily_report_time": "22:30",
    "weekly_report_day": "Sunday",
    "weekly_report_time": "21:30",
    "monthly_report_policy": "last_day",
    "monthly_report_time": "21:30",
    "required_daily_fields": ["movement", "nutrition", "body", "recovery"],
    "not_applicable_daily_fields": []
  },
  "reports": {"formats": ["html", "png", "pdf"]}
}
```

The SQLite owner profile is the source of truth for onboarding and schedule preferences. `schedule plan` never changes OpenClaw; after owner confirmation, its four reviewed commands install gap-check, daily, weekly, and month-end jobs.

Generated artifacts live under `BODYNOTE_HOME/reports`. To send them while OpenClaw uses workspace-only file access, add `--delivery-dir .bodynote-delivery`; only PNG, PDF, and HTML copies are staged.

## Privacy Boundary

One `BODYNOTE_HOME` belongs to one health owner. Keep another person's data in a separate OpenClaw Agent/workspace and a separate runtime directory. Backups contain sensitive health data and must not be published.

See [architecture](docs/ARCHITECTURE.md), [privacy model](docs/PRIVACY.md), [release checklist](docs/RELEASE.md), and [development milestones](docs/DEVELOPMENT_PLAN.md).

Install the local skill into the active OpenClaw workspace:

```bash
openclaw skills install ./skill/bodynote
```

OpenClaw should use pairing/allowlists and `session.identityLinks` for Feishu, QQ, and other channel identities. BodyNote does not duplicate those controls.
