# Onboarding and Scheduling

Read this reference for first-use setup, gap checks, report timing, and delivery.

## First-Use Setup

Collect only information needed to produce useful reports:

- Primary health goal.
- Optional basic profile and relevant constraints.
- Daily record categories the owner wants to track.
- Gap-check time.
- Daily, weekly, and monthly report times.
- Desired HTML, PNG, and PDF outputs.

Use these defaults when the owner has no preference:

```json
{
  "gap_check_time": "20:30",
  "daily_report_time": "22:30",
  "weekly_report_day": "Sunday",
  "weekly_report_time": "21:30",
  "monthly_report_policy": "last_day",
  "monthly_report_time": "21:30",
  "required_daily_fields": ["movement", "nutrition", "body", "recovery"],
  "not_applicable_daily_fields": [],
  "reports": {"formats": ["html", "png", "pdf"]}
}
```

Persist confirmed settings with:

```bash
bodynote-agent onboarding configure --input /local/path/setup.json --json
```

## Gap Check

At the configured time:

1. Read today's applicable record categories.
2. Compare them with the owner's selected requirements.
3. Ask for at most three missing items that materially improve the report.
4. State that the report will still be generated if the owner skips.

Keep the prompt short and non-judgmental.

Use `bodynote-agent gap-check --date YYYY-MM-DD --json` for structured output. Use `bodynote-agent gap-check` for the concise local-date prompt emitted to a scheduled command job.

## OpenClaw Cron Plan

Generate the plan with:

```bash
bodynote-agent schedule plan --json
```

This command is read-only. A ready job contains exact `install_argv` and `install_command` values using the current OpenClaw `cron create`, `--tz`, `--command-argv` or isolated Agent prompt, `--announce`, and `--channel last` interface. Cron mutations require OpenClaw `operator.admin` permission.

Before installation:

1. Require explicit owner confirmation.
2. Execute only jobs with `ready: true`.
3. Run `openclaw cron show <job-id>` after creation and verify the resolved delivery route.
4. For report jobs, verify that the prompt stages files under `.bodynote-delivery` and uses structured message-tool media fields.

OpenClaw cron reference: <https://docs.openclaw.ai/cli/cron>

## Report Run

At report time:

1. Re-check missing data.
2. Freeze the report input window.
3. Build the derived data model.
4. Calculate score, confidence, insights, and actions.
5. Render requested artifacts.
6. Save artifacts in a date-based local directory.
7. Return summary and artifact paths to OpenClaw.

Use idempotency keys based on report type and period so retries update the same report run.

## Delivery

Let OpenClaw own scheduled triggers and channel delivery. BodyNote should not store Feishu or QQ credentials and should not send files directly through channel SDKs.

Do not expose a local web server or QR code by default. Enable local-network viewing only after explicit owner confirmation.
