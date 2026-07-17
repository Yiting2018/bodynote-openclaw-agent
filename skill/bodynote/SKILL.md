---
name: bodynote
description: Use BodyNote when the user wants OpenClaw to record or correct personal health data, inspect a local health cockpit, check missing daily data, explain health patterns, generate or deliver daily/weekly/monthly HTML, PNG, PDF, or JSON reports, configure schedules, or back up and audit the local health runtime. BodyNote is local-first, single-owner, and intended for health management rather than diagnosis or medication decisions.
---

# BodyNote

Use the local `bodynote-agent` runtime for deterministic storage, scoring, safety checks, scheduling, reports, backups, and release-safe exports. Let OpenClaw own channel pairing, sender authorization, sessions, cross-channel identity links, cron execution, and message delivery.

## Preconditions

- Run `bodynote-agent status --json` before invoking a workflow.
- If the runtime is missing, ask the owner to initialize it with `bodynote-agent init`.
- Use only capabilities listed by the status response. Do not invent unavailable commands.
- Treat one BodyNote runtime directory as one health owner.
- If onboarding is incomplete, run `bodynote-agent onboarding status --json` and collect the missing setup fields before installing schedules.

## Workflow

1. Identify the task: onboarding, check-in, correction, gap check, dashboard, report, reference guide, insight, or export.
2. Confirm that the required runtime capability is available.
3. Preserve the user's date, time, units, uncertainty, and original wording when structuring a record.
4. Ask only for missing fields that materially affect the requested result.
5. Pass the OpenClaw message id as `--idempotency-key` for every check-in.
6. Require explicit user confirmation before updating or deleting an event.
7. Generate deterministic score and confidence data before composing an explanation.
8. Keep status, evidence, uncertainty, and next action separate.
9. Describe cross-domain findings as association clues or synchronous changes, never as proven causality.
10. Save private records and generated artifacts locally.
11. Return a short text summary plus artifact paths for OpenClaw to deliver.

For a scheduled gap check, run `bodynote-agent gap-check` without `--json` so a command job can announce the concise owner-facing prompt. Use `--json` when the Agent needs structured missing-category data.

For report delivery, run `report generate` with `--delivery-dir .bodynote-delivery --json`. Send `summary` first, then send only entries in `attachments` through the message tool's structured `filePath` or `path` media field. Never infer attachments from prose or send `report.json`, `manifest.json`, the database, or a directory.

## Reference Routing

- Read `references/agent-contract.md` before calling the local Agent or returning artifacts.
- Read `references/health-model.md` when structuring records, calculating health state, or generating insights.
- Read `references/reports.md` when generating the cockpit, daily report, weekly report, monthly report, or mobile artifact.
- Read `references/scheduling.md` for first-use setup, gap checks, report timing, and delivery behavior.
- Read `references/guides.md` when the owner uploads or selects a health or training guide.
- Read `references/maintenance.md` for backup, restore, privacy audit, migration, and release behavior.

## Safety

- Do not diagnose disease, prescribe treatment, change medication, or promise causality.
- Never fabricate missing measurements, dates, foods, exercises, symptoms, or report findings.
- Never present a cycle forecast as contraception, diagnosis, or a guaranteed date.
- Show cycle support only when the owner explicitly enables tracking. Prefer the
  owner's repeated performance, recovery, and symptom pattern over phase-wide claims;
  never claim that a phase automatically reduces muscle gain or requires lower intensity.
- Treat missing data as lower confidence, not automatically poor health.
- Escalate urgent symptoms or self-harm risk before continuing ordinary tracking.
- Never send the SQLite database, raw record directory, or unrelated health history as a report attachment.
- Do not expose local reports over a network unless the owner explicitly requests it.
- Require explicit confirmation before cron installation, backup restore, or enabling third-party delivery.

## Output Style

- Answer "How am I, why, and what should I do next?" before listing raw numbers.
- Keep daily guidance short and concrete.
- Use green for on track, yellow for mild deviation, red for attention, blue for neutral data, and purple/pink for cycle context.
- Show both health state and data completeness whenever a score is presented.
- Keep score components visible in static PNG/PDF reports. Activity basis should
  distinguish daily movement, duration, resistance frequency/volume, and recorded
  intensity; nutrition basis should distinguish targets, nutrient coverage, and food diversity.
