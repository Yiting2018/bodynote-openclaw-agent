# Changelog

## Unreleased

## 0.3.0 - 2026-07-21

- Add registered domain Handler contracts plus dedicated medical-report and natural-language correction routing.
- Correct occurrence-time priority, completed-sleep date semantics, fuzzy-time disclosure, and explicit time overrides.
- Separate health state from data confidence; use personal targets and baselines instead of record completeness or fixed body scores.
- Build deterministic evidence-based action candidates with safety filtering and priority ranking.
- Personalize cycle support from phase-matched history without prescribing exercise from a phase label alone.
- Generate evidence-specific daily headlines and a single adaptive-height mobile PNG with the complete timeline.
- Auto-migrate existing runtimes on normal commands and add Graywind, migration, determinism, correction, and visual regressions.

## 0.2.0 - 2026-07-18

- Add a local personal food library for reusable foods, branded products, supplements, aliases, and verified nutrition per serving.
- Add reusable meal templates for habitual meals such as a fixed breakfast.
- Resolve meal records against local templates and food aliases, retaining an immutable nutrition snapshot with each historical event.
- Add a local-only food library dashboard page and documented OpenClaw Skill routing for meal matching and confirmation.

- Restore the PC local cockpit with daily/weekly/monthly switching, event timeline,
  report archive, and searchable raw-data inspection.
- Redesign mobile HTML and PNG reports with a more energetic dark visual system,
  richer summary metrics, event timelines, trends, and monthly record heatmaps.
- Keep raw payloads confined to the local cockpit while shareable artifacts use
  filtered summaries.
- Add natural week/month metric comparisons, body-composition trends, explicit score
  basis, cross-domain association clues, and independent raw-data date filters.
- Add personal profile details, history-based cycle forecasts and pre-period reminders.
- Add an owner-approved structured reference library for OpenClaw-extracted guide notes.
- Replace record-count scoring with visible activity duration, resistance volume and
  intensity, nutrition targets and diversity, body, and recovery score components.
- Add conditional cycle support with estimated phase, personal-history signals, and
  cautious nutrition/training guidance to the cockpit and static reports.
- Compact profile details into the cockpit header, add current/previous dimension
  bars with normalized body trends, and group raw data into five practical domains.

## 0.1.0 - 2026-07-16

- Added local single-owner health records, corrections, soft deletion, idempotency, and audit history.
- Added onboarding, gap checks, deterministic health scores, confidence, insights, and actions.
- Added distinct daily, weekly, and monthly analysis and HTML/PNG/PDF/JSON reports.
- Added the responsive local health cockpit and OpenClaw workspace attachment staging.
- Added OpenClaw cron plans for gap checks and scheduled reports.
- Added schema migration, verified backup/restore, privacy audit, and release packaging.
