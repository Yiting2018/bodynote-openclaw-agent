# Agent Contract

Read this reference before calling the local runtime or returning generated artifacts.

## Ownership Boundary

- Treat one `BODYNOTE_HOME` as one owner profile.
- Rely on OpenClaw for pairing, allowlists, sessions, and `session.identityLinks`.
- Do not create or merge channel identities inside BodyNote.
- Require a separate runtime directory for another person.

## Runtime Discovery

Run:

```bash
bodynote-agent status --json
```

The response declares available capabilities. Invoke only listed capabilities. The release runtime exposes initialization, event management, onboarding, gap checks, deterministic analysis, reports, dashboard generation, structured reference cards, schedule planning, backups, privacy audit, and release packaging.

## Check-In Command Contract

BodyNote uses one OpenClaw conversation agent, one deterministic intent router,
and domain handlers such as `MealHandler`, `ExerciseHandler`, `SleepHandler`,
`BodyHandler`, and `CycleHandler`. Handlers extract domain fields; shared services
own time resolution, validation, safety rules, persistence, scoring, and reports.
Do not create a separate autonomous language-model agent for every health domain.

For completed sleep, distinguish the message time from the sleep date. A natural
language record such as “昨晚睡了 7 小时” belongs to the day the owner woke up and
must be rendered as “昨夜睡眠”, not with the message's late-evening clock. A future
statement such as “今晚想睡 8 小时” is a plan and must not be saved as completed sleep.

Record natural-language text. Always use the stable OpenClaw message id as the idempotency key:

```bash
bodynote-agent checkin \
  --text "今天走了8000步" \
  --source openclaw \
  --idempotency-key "<channel>:<message-id>" \
  --json
```

When the owner gives an exact occurrence time outside the sentence, pass it as
an ISO 8601 override instead of rewriting the text:

```bash
bodynote-agent checkin --text "吃了三文鱼" --at "2026-07-16T18:25:00+08:00" --json
```

Record a structured event from a local JSON file:

```bash
bodynote-agent checkin --input /local/path/event.json --json
```

List or inspect events:

```bash
bodynote-agent events --date 2026-07-16 --json
bodynote-agent event show <event-id> --json
```

After explicit user confirmation, apply a JSON patch or soft-delete an event:

```bash
bodynote-agent event update <event-id> --input /local/path/patch.json --json
bodynote-agent event delete <event-id> --confirm --json
```

The structured check-in file uses:

```json
{
  "event_type": "body",
  "occurred_at": "2026-07-16T08:00:00+08:00",
  "payload": {"weight_kg": 61.2},
  "source": "openclaw",
  "idempotency_key": "feishu:message-id",
  "raw_text": "今早体重61.2kg",
  "confidence": 0.98
}
```

Every successful check-in response contains:

```json
{
  "ok": true,
  "recorded": true,
  "duplicate": false,
  "summary": "已记录运动：walking 8000 步。",
  "event": {},
  "follow_up_question": null,
  "warnings": [],
  "safety": null
}
```

If `duplicate` is true, acknowledge the existing record instead of presenting it as a new save.

## Onboarding and Gap Check Contract

Read the current setup before prompting the owner:

```bash
bodynote-agent onboarding status --json
```

Write confirmed settings from a local JSON object:

```bash
bodynote-agent onboarding configure --input /local/path/setup.json --json
```

The primary goal is required to complete onboarding. The owner may select any non-empty subset of `movement`, `nutrition`, `body`, `recovery`, `blood_pressure`, and `blood_glucose` as daily requirements. Use `not_applicable_daily_fields` only for categories the owner confirms do not apply; leave ordinary unselected categories unplanned. Blood pressure and blood glucose are opt-in, not universal defaults.

Check the selected requirements for one local date:

```bash
bodynote-agent gap-check --date 2026-07-16 --json
```

The result separates `required`, `completed`, `missing`, `not_planned`, and `not_applicable`. It asks for at most three missing categories and always returns `report_can_continue: true` after onboarding.
When cycle tracking is enabled, the result also contains `cycle_forecast`. Announce an
upcoming reminder only when `reminder_due` is true and preserve its disclaimer.

Build, but do not install, the OpenClaw schedule:

```bash
bodynote-agent schedule plan --json
```

Only execute a job's `install_argv` after explicit owner confirmation and OpenClaw delivery-route review. Ignore jobs with `ready: false`.

## Analysis and Report Contract

Build deterministic analysis without artifacts:

```bash
bodynote-agent analyze --type daily --period 2026-07-16 --json
bodynote-agent analyze --type weekly --period 2026-07-16 --json
bodynote-agent analyze --type monthly --period 2026-07 --json
```

Generate artifacts and stage only sendable copies inside the OpenClaw workspace:

```bash
bodynote-agent report generate \
  --type daily \
  --period 2026-07-16 \
  --delivery-dir .bodynote-delivery \
  --json
```

Read `summary` and `attachments` from the response. Use structured media fields to send each attachment. Do not parse paths out of text. Repeated generation with unchanged inputs returns `duplicate: true` and stable artifact paths.

Refresh the local static cockpit with:

```bash
bodynote-agent dashboard build --json
```

Store a structured guide card only after the owner approves the source and extracted
summary:

```bash
bodynote-agent reference add --input /local/path/guide-card.json --json
bodynote-agent reference list --enabled-only --json
bodynote-agent reference disable <guide-id> --json
```

## Failure Behavior

- Return structured errors without exposing stack traces or raw database contents.
- Do not create duplicate records when OpenClaw retries the same message or scheduled run.
- Do not generate a report from another runtime directory.
- If identity or authorization is uncertain, stop before calling BodyNote and resolve it in OpenClaw.
- Treat deletion as a confirmed soft delete. Do not edit or delete from ambiguous natural-language references without first resolving one exact event id.
- Treat scheduled monthly runs returning `skipped: true` as `NO_REPLY`.
