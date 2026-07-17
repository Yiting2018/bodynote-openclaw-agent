# Cockpit and Reports

Read this reference when generating the local cockpit or daily, weekly, and monthly artifacts.

## Health Cockpit

Make the first screen answer:

1. What is today's state?
2. Why?
3. What should the owner do next?

Show a health halo, score, data completeness, up to three reasons, movement/nutrition/body/recovery modules, today's actions, and report history. Do not lead with tables, JSON, IDs, or database terminology.

## Daily Report

Focus on closing today and preparing tomorrow:

- Overall state and data completeness.
- Best completion and biggest gap.
- Movement, nutrition, body, recovery, and cycle context.
- One to three insight cards.
- One to three actions for tomorrow.

Use a 1080x1920 PNG as the primary mobile artifact. Generate HTML as the source/preview and PDF as the fuller archive.

The report directory contains `report.json`, optional `report.html`, `report.png`, `report.pdf`, and `manifest.json`. Only PNG, PDF, and HTML may appear in the delivery attachment list.

## Weekly Report

Focus on pattern and sustainability:

- Seven-day trend and a longer baseline when available.
- Aerobic, strength, rest, and body-part structure.
- Nutrition timing and weekday/weekend patterns.
- Sleep, fatigue, soreness, mood, and cycle context.
- A specific next-week plan.

Do not stretch the daily layout across seven days.

## Monthly Report

Focus on body change, goal progress, and follow-up:

- Weight and body-composition changes.
- Training capacity and nutrition consistency.
- Cycle pattern when applicable and sufficiently recorded.
- Medical report actions and risk follow-up.
- One primary next-month goal.

Downgrade to a record summary when evidence is insufficient.

## Color Semantics

- Green: completed, good, on track.
- Yellow: mild deviation or attention soon.
- Red: safety or high-priority attention.
- Blue: neutral information and history.
- Purple/pink: menstrual-cycle context.

Keep report artifacts filtered to the current local owner. Never attach the database or raw record directory.

When OpenClaw restricts local media to its workspace, pass `--delivery-dir .bodynote-delivery`. BodyNote copies only allowlisted report artifacts there and returns the staged paths. Feishu supports image and file delivery. QQ C2C and group targets support local rich media; QQ guild channels require text or remote-URL images, so keep BodyNote local-first and fall back to the summary text there.
