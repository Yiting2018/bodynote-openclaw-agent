# Cockpit and Reports

Read this reference when generating the local cockpit or daily, weekly, and monthly artifacts.

## Health Cockpit

Make the first screen answer:

1. What is today's state?
2. Why?
3. What should the owner do next?

The cockpit is a PC-first local workspace with four views. The global day/week/month
switch changes metrics, charts, summaries, and the timeline together. Week means the
current natural week starting Monday; month means the current natural month.

1. Overview: compact owner tags, state, score, confidence, true-unit metrics,
   current/previous dimension-score bars, normalized body trends, visible score basis,
   conditional cycle support, and period events.
2. Timeline: events grouped by their real occurrence date across the selected natural period, with a type filter.
3. Trends: activity, nutrition, body, and recovery comparisons, association clues, opportunities, risks, guides, and archive.
4. Raw data: searchable event payloads grouped into activity/training, nutrition,
   body status, sleep/feelings, and medical records, with source context, confidence,
   revisions, timestamps, and independent today/week/month/custom filters. Cycle
   records are a body-status subtype, not a standalone top-level domain.

Do not lead the owner-facing view with tables, JSON, IDs, or database terminology. Raw fields belong only to the explicit local backend-data view and must never be copied into a mobile report or delivery attachment.

## Daily Report

Focus on closing today and preparing tomorrow:

- Overall state and data completeness.
- Best completion and biggest gap.
- Movement, nutrition, body, recovery, and conditional cycle context.
- Visible score components; static artifacts must never hide essential evidence behind interaction.
- One to three insight cards.
- One to three actions for tomorrow.

Use a 1080x1920 PNG as the primary mobile artifact. Generate responsive HTML as the interactive preview and PDF as the fuller archive. The daily mobile report should include a compact event timeline so the owner can see what actually happened, not only derived scores.

The report directory contains `report.json`, optional `report.html`, `report.png`, `report.pdf`, and `manifest.json`. Only PNG, PDF, and HTML may appear in the delivery attachment list.

## Weekly Report

Focus on pattern and sustainability:

- Natural-week change versus the preceding equal-length period.
- Aerobic, strength, rest, and body-part structure.
- Nutrition timing and weekday/weekend patterns.
- Sleep, fatigue, soreness, mood, and cycle context.
- A specific next-week plan.
- Sample size, completeness, confidence, and a caveat for every cross-domain clue.
- Dimension-score bars and body-composition trends in the generated PNG/PDF, not only the cockpit.

Do not stretch the daily layout across seven days.

## Monthly Report

Focus on body change, goal progress, and follow-up:

- Weight and body-composition changes.
- Training capacity and nutrition consistency.
- Cycle pattern when applicable and sufficiently recorded.
- Medical report actions and risk follow-up.
- One primary next-month goal.

Downgrade to a record summary when evidence is insufficient.

Use wording such as "同步变化", "关联线索", and "可能解释". Do not infer that
protein caused muscle gain, activity caused weight change, or sleep caused fatigue
from a short local time series.

## Color Semantics

- Green: completed, good, on track.
- Yellow: mild deviation or attention soon.
- Red: safety or high-priority attention.
- Blue: neutral information and history.
- Purple/pink: menstrual-cycle context.

Keep report artifacts filtered to the current local owner. Never attach the database or raw record directory.

When OpenClaw restricts local media to its workspace, pass `--delivery-dir .bodynote-delivery`. BodyNote copies only allowlisted report artifacts there and returns the staged paths. Feishu supports image and file delivery. QQ C2C and group targets support local rich media; QQ guild channels require text or remote-URL images, so keep BodyNote local-first and fall back to the summary text there.
